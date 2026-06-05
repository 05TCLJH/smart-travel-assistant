"""Trip planning routes and static map preview helpers."""

from __future__ import annotations

import asyncio
import json
import socket
import ssl
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException, Query, Request as FastAPIRequest
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from backend.core.api_response import success_response
from backend.core.runtime_context import runtime_keys_scope
from backend.core.runtime_owner import ensure_runtime_owner, read_runtime_owner
from backend.core.settings import amap_key, trip_sync_route_enabled
from backend.runtime.state_store import runtime_state_store
from backend.runtime.task_manager import TripTaskManager
from backend.services.factory import create_travel_service


router = APIRouter()
task_manager = TripTaskManager()

TASK_NOT_FOUND = "Task not found"
TASK_CANCELLED = "Task cancelled"
TASK_CREATED = "Task created"
TRIP_SUCCESS = "Trip generated successfully"


class TripPlanRequest(BaseModel):
    destination: str
    start_date: str
    days: int
    budget: float
    persona: dict | None = None
    amap_api_key: str | None = None
    bailian_api_key: str | None = None

    def trip_payload(self) -> dict[str, object]:
        return {
            "destination": self.destination,
            "start_date": self.start_date,
            "days": self.days,
            "budget": self.budget,
        }

    def request_payload(self) -> dict[str, object]:
        return {"trip_request": self.trip_payload(), "persona": self.persona or {}}

    def runtime_keys(self) -> dict[str, str]:
        keys: dict[str, str] = {}
        amap_value = str(self.amap_api_key or "").strip()
        bailian_value = str(self.bailian_api_key or "").strip()
        if amap_value:
            keys["amap_api_key"] = amap_value
        if bailian_value:
            keys["bailian_api_key"] = bailian_value
        return keys


def _require_runtime_owner(request: FastAPIRequest) -> str:
    owner_id = read_runtime_owner(request)
    if owner_id:
        return owner_id
    raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)


def _apply_private_no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Vary"] = "Cookie"
    return response


def _safe_static_map_failure(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"Static map service returned HTTP {exc.code}."
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, socket.timeout | TimeoutError):
            return "Static map service timed out."
        if isinstance(reason, socket.gaierror):
            return "Static map DNS lookup failed."
        if isinstance(reason, ssl.SSLError):
            return "Static map SSL handshake failed."
        if isinstance(reason, ConnectionResetError):
            return "Static map connection was reset by the remote host."
        if isinstance(reason, ConnectionRefusedError):
            return "Static map connection was refused."
        if isinstance(reason, OSError):
            detail = str(reason).strip()
            return f"Static map network error: {detail}" if detail else "Static map network error."
        detail = str(reason).strip()
        return f"Static map service is temporarily unreachable: {detail}" if detail else "Static map service is temporarily unreachable."
    return "Static map request failed unexpectedly."


def _is_retryable_static_map_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return int(exc.code) >= 500
    if not isinstance(exc, URLError):
        return False
    reason = exc.reason
    if isinstance(reason, socket.timeout | TimeoutError | socket.gaierror | ssl.SSLError):
        return True
    return isinstance(reason, OSError)


def _fetch_static_map_content(static_map_url: str, *, attempts: int = 2, timeout: int = 15) -> tuple[bytes, str]:
    remote_request = Request(static_map_url, headers={"User-Agent": "smart-travel-assistant/3.0"})
    last_exc: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            with urlopen(remote_request, timeout=timeout) as remote:
                return remote.read(), remote.headers.get("Content-Type", "image/png")
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_retryable_static_map_error(exc):
                break
            time.sleep(0.25)
    assert last_exc is not None
    raise last_exc


@router.post("/plan")
async def create_trip_plan(request: TripPlanRequest, http_request: FastAPIRequest) -> JSONResponse:
    task_id = str(uuid.uuid4())
    response = JSONResponse(success_response(None, TASK_CREATED, task_id=task_id))
    owner_id = ensure_runtime_owner(http_request, response)
    task_manager.enqueue(
        task_id,
        owner_id=owner_id,
        request_payload=request.request_payload(),
        runtime_keys=request.runtime_keys(),
    )
    return response


@router.post("/cancel/{task_id}")
async def cancel_trip_plan(task_id: str, request: FastAPIRequest) -> dict:
    owner_id = _require_runtime_owner(request)
    task = task_manager.get_snapshot(task_id, owner_id=owner_id)
    if not task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)
    if task.status not in {"queued", "running"}:
        return success_response({"status": task.status}, "Task status already settled")
    task_manager.cancel(task_id)
    return success_response({"status": "cancelled"}, "Task cancelled successfully")


@router.post("/plan/sync")
async def create_trip_plan_sync(request: TripPlanRequest, http_request: FastAPIRequest) -> JSONResponse:
    if not trip_sync_route_enabled():
        raise HTTPException(status_code=404, detail="Synchronous trip planning is disabled for deployment safety.")
    owner_id = read_runtime_owner(http_request) or uuid.uuid4().hex
    service = create_travel_service()
    with runtime_keys_scope(owner_id=owner_id, **request.runtime_keys()):
        result = await asyncio.to_thread(
            service.generate,
            request.trip_payload(),
            request.persona or {},
            None,
            None,
            request.runtime_keys(),
            owner_id=owner_id,
            session_id=str(uuid.uuid4()),
        )
    response = JSONResponse(success_response(result, TRIP_SUCCESS, task_id=None))
    ensure_runtime_owner(http_request, response, owner_id=owner_id)
    return response


@router.get("/progress/{task_id}")
async def get_progress(
    task_id: str,
    request: FastAPIRequest,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    owner_id = _require_runtime_owner(request)

    async def event_generator():
        snapshot = task_manager.get_snapshot(task_id, owner_id=owner_id)
        if snapshot is None:
            yield f"data: {json.dumps({'type': 'error', 'message': TASK_NOT_FOUND}, ensure_ascii=False)}\n\n"
            return

        sent_count = min(max(after, 0), len(snapshot.progress_messages))
        seen_version = snapshot.version
        while True:
            snapshot = task_manager.get_snapshot(task_id, owner_id=owner_id)
            if snapshot is None:
                break
            messages = list(snapshot.progress_messages)
            while sent_count < len(messages):
                raw = messages[sent_count]
                if isinstance(raw, str):
                    payload = {"type": "progress", "message": raw, "stage": None}
                else:
                    payload = {
                        "type": "progress",
                        "message": str(raw.get("message", "")),
                        "stage": raw.get("stage"),
                        "step_id": raw.get("step_id"),
                        "status": raw.get("status", "running"),
                        "label": raw.get("label"),
                    }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                sent_count += 1
            if snapshot.status == "completed":
                yield f"data: {json.dumps({'type': 'complete', 'result': snapshot.result}, ensure_ascii=False)}\n\n"
                break
            if snapshot.status == "failed":
                yield f"data: {json.dumps({'type': 'error', 'message': snapshot.error}, ensure_ascii=False)}\n\n"
                break
            if snapshot.status == "cancelled":
                yield f"data: {json.dumps({'type': 'cancelled', 'message': TASK_CANCELLED}, ensure_ascii=False)}\n\n"
                break
            updated = await asyncio.to_thread(task_manager.wait_for_update, task_id, seen_version, 15.0)
            if updated is None:
                break
            if updated.version == seen_version:
                yield ": keep-alive\n\n"
            else:
                seen_version = updated.version

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/result/{task_id}")
async def get_result(task_id: str, request: FastAPIRequest) -> dict:
    owner_id = _require_runtime_owner(request)
    task = task_manager.get_snapshot(task_id, owner_id=owner_id)
    if not task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)
    if task.status in {"queued", "running"}:
        return {"status": task.status, "message": "Trip generation is still in progress"}
    if task.status == "failed":
        raise HTTPException(status_code=500, detail=task.error)
    if task.status == "cancelled":
        return {"status": "cancelled", "message": TASK_CANCELLED, "data": None}
    return {"status": "completed", "data": task.result}


def _svg_placeholder(message: str) -> Response:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="760" height="360" viewBox="0 0 760 360">
    <rect width="760" height="360" fill="#eef6f5"/>
    <rect x="24" y="24" width="712" height="312" rx="20" fill="#ffffff" stroke="#cfe1df"/>
    <text x="48" y="96" font-size="28" fill="#1f5c56" font-family="Arial, sans-serif">Map preview unavailable</text>
    <text x="48" y="146" font-size="20" fill="#547d79" font-family="Arial, sans-serif">{message}</text>
    </svg>"""
    return _apply_private_no_store(Response(content=svg.encode("utf-8"), media_type="image/svg+xml"))


def _extract_points_from_preview(markers: str | None, paths: str | None) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for marker in (markers or "").split("|"):
        raw = marker.strip()
        if not raw or ":" not in raw:
            continue
        coord = raw.rsplit(":", 1)[-1]
        if "," not in coord:
            continue
        try:
            lng, lat = coord.split(",", 1)
            points.append((float(lng), float(lat)))
        except ValueError:
            continue
    path_raw = str(paths or "").split(":")[-1] if paths else ""
    for item in path_raw.split(";"):
        raw = item.strip()
        if "," not in raw:
            continue
        try:
            lng, lat = raw.split(",", 1)
            point = (float(lng), float(lat))
            if point not in points:
                points.append(point)
        except ValueError:
            continue
    return points


def _svg_route_preview(message: str, markers: str | None, paths: str | None) -> Response:
    points = _extract_points_from_preview(markers, paths)
    if not points:
        return _svg_placeholder(message)

    lngs = [point[0] for point in points]
    lats = [point[1] for point in points]
    min_lng, max_lng = min(lngs), max(lngs)
    min_lat, max_lat = min(lats), max(lats)
    lng_span = max(max_lng - min_lng, 0.01)
    lat_span = max(max_lat - min_lat, 0.01)

    def project(point: tuple[float, float]) -> tuple[float, float]:
        lng, lat = point
        x = 60 + (lng - min_lng) / lng_span * 640
        y = 300 - (lat - min_lat) / lat_span * 220
        return round(x, 2), round(y, 2)

    projected = [project(point) for point in points]
    polyline = " ".join(f"{x},{y}" for x, y in projected)
    marker_nodes = []
    for index, (x, y) in enumerate(projected[:8], start=1):
        marker_nodes.append(
            f'<circle cx="{x}" cy="{y}" r="8" fill="#E45B5B"/><text x="{x}" y="{y + 4}" text-anchor="middle" font-size="10" fill="#ffffff" font-family="Arial, sans-serif">{index}</text>'
        )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="760" height="360" viewBox="0 0 760 360">
    <rect width="760" height="360" fill="#eef6f5"/>
    <rect x="24" y="24" width="712" height="312" rx="20" fill="#ffffff" stroke="#cfe1df"/>
    <polyline points="{polyline}" fill="none" stroke="#2F7CF6" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    {''.join(marker_nodes)}
    <text x="48" y="60" font-size="18" fill="#1f5c56" font-family="Arial, sans-serif">Route preview</text>
    <text x="48" y="86" font-size="13" fill="#547d79" font-family="Arial, sans-serif">{message}</text>
    </svg>"""
    return _apply_private_no_store(Response(content=svg.encode("utf-8"), media_type="image/svg+xml"))


@router.get("/static-map")
async def get_static_map(
    request: FastAPIRequest,
    ticket: str | None = Query(default=None),
    markers: str | None = Query(default=None),
    paths: str | None = Query(default=None),
    labels: str | None = Query(default=None),
    location: str | None = Query(default=None),
    size: str = Query(default="760*360"),
    zoom: str | None = Query(default=None),
) -> Response:
    owner_id = read_runtime_owner(request)
    runtime_key = ""

    if ticket:
        ticket_payload = runtime_state_store.get_static_map_ticket(owner_id, ticket) if owner_id else None
        if ticket_payload is None:
            return _svg_placeholder("Static map ticket is invalid, expired, or belongs to another runtime owner.")
        runtime_key = str(ticket_payload["amap_api_key"]).strip()
        payload = ticket_payload["payload"]
        markers = str(payload.get("markers") or "").strip() or None
        paths = str(payload.get("paths") or "").strip() or None
        labels = str(payload.get("labels") or "").strip() or None
        location = str(payload.get("location") or "").strip() or None
        size = str(payload.get("size") or size).strip() or size
        zoom = str(payload.get("zoom") or "").strip() or None

    with runtime_keys_scope(amap_api_key=runtime_key or None, owner_id=owner_id or None):
        key = amap_key()
    if not key:
        return _svg_placeholder("Amap key is not available for this preview.")

    params: dict[str, str] = {"size": size, "key": key}
    if markers:
        params["markers"] = markers
    if paths:
        params["paths"] = paths
    if labels:
        params["labels"] = labels
    if location:
        params["location"] = location
    if zoom:
        params["zoom"] = zoom
    if not markers and not paths and not labels and (not location or not zoom):
        return _svg_placeholder("Missing static map parameters.")

    static_map_url = f"https://restapi.amap.com/v3/staticmap?{urlencode(params)}"
    try:
        content, content_type = _fetch_static_map_content(static_map_url)
        if "json" in content_type.lower():
            try:
                payload = json.loads(content.decode("utf-8"))
                info = str(payload.get("info", "Static map service returned an error"))
            except Exception:
                info = "Static map service returned an error"
            return _svg_route_preview(f"Static map unavailable: {info}", markers, paths)
        return _apply_private_no_store(Response(content=content, media_type=content_type))
    except Exception as exc:
        return _svg_route_preview(_safe_static_map_failure(exc), markers, paths)
