"""System status and runtime configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.api_key_specs import (
    classify_service_failure,
    issues_to_field_map,
    list_key_specs_public,
    validate_runtime_key_updates,
)
from backend.core.api_response import failure_response, success_response
from backend.core.runtime_owner import ensure_runtime_owner
from backend.core.settings import (
    amap_enabled,
    bailian_enabled,
    get_runtime_config,
    has_backend_key_configured,
    travel_context_mcp_enabled,
)
from backend.services.vision_service import VisionService


router = APIRouter()


class RuntimeConfigPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    amap_api_key: str | None = Field(default=None, description="Amap API key")
    amap_web_service_key: str | None = Field(default=None, description="Legacy alias for amap_api_key")
    amap_mcp_api_key: str | None = Field(default=None, description="Legacy alias for amap_api_key")
    bailian_api_key: str | None = Field(default=None, description="DashScope/Bailian API key")


def _pick_amap_key(payload: RuntimeConfigPayload) -> str | None:
    for name in ("amap_api_key", "amap_mcp_api_key", "amap_web_service_key"):
        if name not in payload.model_fields_set:
            continue
        value = getattr(payload, name)
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            return cleaned
    return None


def _pick_bailian_key(payload: RuntimeConfigPayload) -> str | None:
    if "bailian_api_key" not in payload.model_fields_set:
        return None
    value = payload.bailian_api_key
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def _build_status_payload() -> dict[str, object]:
    vision_enabled = VisionService().enabled
    trip_live_enabled = amap_enabled()
    runtime_config = get_runtime_config()
    mode = "hybrid" if has_backend_key_configured() else "demo"

    notes = [
        "BYOK keys stay in the current browser session and are only copied into short-lived runtime task records while a background job is executing.",
        "Queued trip tasks now run from shared runtime state instead of the request worker, so SSE/result polling can survive normal worker handoff.",
        "This deployment profile is designed for a single public app instance with short-lived runtime state, which matches a typical Hugging Face Space setup.",
    ]
    if mode == "demo":
        notes.append("Live map or vision features require the user to provide their own keys in the current session.")
    else:
        notes.append("Backend environment keys can still be used as a fallback, but per-session keys override them for the current runtime chain.")
    if trip_live_enabled:
        notes.append("Map, weather, and POI data prefer Amap-backed live services when a key is available.")
    else:
        notes.append("Amap live features are disabled, so map and weather views may fall back to local/demo data.")
    if travel_context_mcp_enabled():
        notes.append("Travel Context MCP is enabled behind deployment-level authorization and runtime-owner isolation.")
    else:
        notes.append("Travel Context MCP is disabled by default to avoid exposing internal planning context.")
    if vision_enabled:
        notes.append("Vision recognition is enabled.")
    else:
        notes.append("Vision recognition is unavailable until a Bailian/Qwen key is provided.")
    return {
        "app_mode": mode,
        "trip_live_enabled": trip_live_enabled,
        "amap_enabled": amap_enabled(),
        "direct_amap_enabled": amap_enabled(),
        "bailian_enabled": bailian_enabled(),
        "vision_enabled": vision_enabled,
        "llm_enabled": vision_enabled,
        "report_enabled": True,
        "runtime_config": runtime_config,
        "notes": notes,
    }


@router.put("/runtime-config")
async def save_runtime_config(payload: RuntimeConfigPayload) -> dict:
    amap_value = _pick_amap_key(payload)
    bailian_value = _pick_bailian_key(payload)

    if amap_value is None and bailian_value is None:
        return success_response(
            {"runtime_config": get_runtime_config(), "session_only": True},
            "BYOK validation completed. Keys are not written into long-lived backend config.",
        )

    validation_issues = validate_runtime_key_updates(
        amap_api_key=amap_value if amap_value is not None else None,
        bailian_api_key=bailian_value if bailian_value is not None else None,
    )
    if validation_issues:
        return failure_response(
            {
                "runtime_config": get_runtime_config(),
                "validation_errors": issues_to_field_map(validation_issues),
            },
            "Key format validation failed.",
        )

    updated: list[str] = []
    if amap_value is not None:
        updated.append("amap")
    if bailian_value is not None:
        updated.append("bailian")

    return success_response(
        {
            "runtime_config": get_runtime_config(),
            "session_only": True,
            "validated": updated,
        },
        f"Validated keys: {', '.join(updated)}",
    )


@router.get("/status")
async def status(request: Request) -> JSONResponse:
    response = JSONResponse(success_response(_build_status_payload(), "System status loaded"))
    ensure_runtime_owner(request, response)
    return response


@router.get("/runtime-config")
async def runtime_config() -> dict:
    return success_response(get_runtime_config(), "Runtime config loaded")


@router.get("/key-specs")
async def key_specs() -> dict:
    return success_response({"specs": list_key_specs_public()}, "Key specs loaded")


@router.get("/progress-catalog")
async def progress_catalog() -> dict:
    from backend.runtime.progress_catalog import list_steps_public

    return success_response({"steps": list_steps_public()}, "Progress catalog loaded")


@router.post("/classify-failure")
async def classify_failure(payload: dict) -> dict:
    message = str(payload.get("message", "")).strip()
    hint = str(payload.get("hint", "")).strip()
    return success_response(classify_service_failure(message, hint=hint or None), "ok")
