"""Internal travel context MCP service."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.agents.mcp_prompts import build_prompt_messages
from backend.core.runtime_owner import read_runtime_owner
from backend.core.settings import travel_context_mcp_enabled, travel_context_mcp_token
from backend.mcp.streamable_http_client import MCP_PROTOCOL_VERSION
from backend.mcp.travel_context_store import travel_context_store


router = APIRouter()


def _jsonrpc_result(payload_id: Any, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": payload_id, "result": result})


def _jsonrpc_error(payload_id: Any, code: int, message: str, *, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": payload_id, "error": {"code": code, "message": message}}, status_code=status_code)


def _resource_text(uri: str, contents: Any) -> list[dict[str, Any]]:
    return [{"uri": uri, "mimeType": "application/json", "text": json.dumps(contents, ensure_ascii=False, indent=2)}]


def _base_prompt_context(owner_id: str, session_id: str) -> dict[str, Any]:
    snapshot = travel_context_store.snapshot(owner_id, session_id) if session_id else {}
    return {
        "session_id": session_id,
        "trip_request": snapshot.get("trip_request", {}),
        "persona": snapshot.get("persona", {}),
        "weather": snapshot.get("weather", {}),
        "map_data": snapshot.get("map_data", {}),
        "research_brief": snapshot.get("research_brief", {}),
        "candidate_pois": snapshot.get("candidate_pois", []),
        "candidate_guard": snapshot.get("candidate_guard", {}),
        "plan": snapshot.get("plan", {}),
        "transport_plan": snapshot.get("transport_plan", {}),
        "lodging_recommendations": snapshot.get("lodging_recommendations", []),
        "food_recommendations": snapshot.get("food_recommendations", []),
        "review_feedback": snapshot.get("review_feedback", {}),
    }


def _prompt_messages(owner_id: str, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    session_id = str(arguments.get("session_id", "")).strip()
    context = _base_prompt_context(owner_id, session_id)
    messages = build_prompt_messages(name, context)
    for message in messages:
        content = message.get("content")
        if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), dict):
            content["text"] = json.dumps(content["text"], ensure_ascii=False)
    return messages


def _authorize(request: Request, payload_id: Any) -> tuple[str, JSONResponse | None]:
    if not travel_context_mcp_enabled():
        return "", _jsonrpc_error(payload_id, -32004, "Travel Context MCP is disabled", status_code=404)
    expected_token = travel_context_mcp_token()
    provided_token = str(request.headers.get("x-travel-context-token", "")).strip()
    if not expected_token or provided_token != expected_token:
        return "", _jsonrpc_error(payload_id, -32001, "Travel Context MCP authorization failed", status_code=403)
    owner_id = read_runtime_owner(request)
    if not owner_id:
        return "", _jsonrpc_error(payload_id, -32002, "Missing runtime owner scope", status_code=403)
    return owner_id, None


@router.post("/travel-context")
async def travel_context_mcp(request: Request) -> JSONResponse:
    payload = await request.json()
    payload_id = payload.get("id")
    method = str(payload.get("method", "")).strip()
    params = payload.get("params", {}) if isinstance(payload.get("params"), dict) else {}

    owner_id, error = _authorize(request, payload_id)
    if error is not None:
        return error

    if method == "initialize":
        return _jsonrpc_result(
            payload_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {"name": "travel-context-mcp", "version": "2.0.0"},
            },
        )
    if method == "notifications/initialized":
        return JSONResponse({}, status_code=202)
    if method == "tools/list":
        return _jsonrpc_result(
            payload_id,
            {
                "tools": [
                    {
                        "name": "get_trip_snapshot",
                        "description": "Read the full stored travel planning snapshot for a session owned by the current runtime owner.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"session_id": {"type": "string"}},
                            "required": ["session_id"],
                        },
                        "annotations": {"readOnlyHint": True},
                    },
                    {
                        "name": "export_session_bundle",
                        "description": "Export persona, trip request, candidate POIs, plan, and review for a session owned by the current runtime owner.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"session_id": {"type": "string"}},
                            "required": ["session_id"],
                        },
                        "annotations": {"readOnlyHint": True},
                    },
                ]
            },
        )
    if method == "tools/call":
        name = str(params.get("name", "")).strip()
        arguments = params.get("arguments", {}) if isinstance(params.get("arguments"), dict) else {}
        session_id = str(arguments.get("session_id", "")).strip()
        snapshot = travel_context_store.snapshot(owner_id, session_id)
        if not snapshot:
            return _jsonrpc_error(payload_id, -32003, "Session not found", status_code=404)
        if name == "get_trip_snapshot":
            return _jsonrpc_result(payload_id, {"content": [{"type": "text", "text": json.dumps(snapshot, ensure_ascii=False)}], "structuredContent": snapshot})
        if name == "export_session_bundle":
            bundle = {
                "session_id": session_id,
                "persona": snapshot.get("persona", {}),
                "trip_request": snapshot.get("trip_request", {}),
                "candidate_pois": snapshot.get("candidate_pois", []),
                "plan": snapshot.get("plan", {}),
                "review_feedback": snapshot.get("review_feedback", {}),
            }
            return _jsonrpc_result(payload_id, {"content": [{"type": "text", "text": json.dumps(bundle, ensure_ascii=False)}], "structuredContent": bundle})
        return _jsonrpc_error(payload_id, -32601, f"Unknown tool: {name}")
    if method == "resources/list":
        resources = []
        for session in travel_context_store.list_sessions(owner_id):
            session_id = session["session_id"]
            resources.extend(
                [
                    {"uri": f"travel://sessions/{session_id}", "name": f"Session {session_id}", "mimeType": "application/json"},
                    {"uri": f"travel://sessions/{session_id}/persona", "name": f"Session {session_id} persona", "mimeType": "application/json"},
                    {"uri": f"travel://sessions/{session_id}/trip_request", "name": f"Session {session_id} trip request", "mimeType": "application/json"},
                    {"uri": f"travel://sessions/{session_id}/candidate_pois", "name": f"Session {session_id} candidate pois", "mimeType": "application/json"},
                    {"uri": f"travel://sessions/{session_id}/plan", "name": f"Session {session_id} plan", "mimeType": "application/json"},
                    {"uri": f"travel://sessions/{session_id}/review_feedback", "name": f"Session {session_id} review", "mimeType": "application/json"},
                ]
            )
        return _jsonrpc_result(payload_id, {"resources": resources})
    if method == "resources/read":
        uri = str(params.get("uri", "")).strip()
        payload = travel_context_store.read_resource(owner_id, uri)
        return _jsonrpc_result(payload_id, {"contents": _resource_text(uri, payload.get("contents"))})
    if method == "prompts/list":
        return _jsonrpc_result(
            payload_id,
            {
                "prompts": [
                    {
                        "name": "plan-travel-itinerary",
                        "description": "Generate a grounded itinerary and keep each section tied to the user's actual data and the current plan.",
                        "arguments": [{"name": "session_id", "required": True}],
                    },
                    {
                        "name": "audit-grounding",
                        "description": "Audit grounded POI usage and verify each section is tied to the current user context and generated plan.",
                        "arguments": [{"name": "session_id", "required": True}],
                    },
                ]
            },
        )
    if method == "prompts/get":
        name = str(params.get("name", "")).strip()
        arguments = params.get("arguments", {}) if isinstance(params.get("arguments"), dict) else {}
        return _jsonrpc_result(payload_id, {"description": name, "messages": _prompt_messages(owner_id, name, arguments)})
    return _jsonrpc_error(payload_id, -32601, f"Unknown method: {method}")
