from __future__ import annotations

import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.core.runtime_owner import RUNTIME_OWNER_COOKIE
from backend.main import create_app


def _sample_snapshot() -> dict:
    return {
        "trip_request": {
            "destination": "杭州",
            "days": 3,
            "budget": 3200,
        },
        "persona": {
            "travel_style": "城市慢游",
            "transport_preference": "地铁+步行",
        },
        "weather": {"rating": "适中", "advice": "午后可能有阵雨，室内外行程搭配更稳妥。"},
        "map_data": {"pois": [{"name": "西湖", "type": "风景名胜"}]},
        "research_brief": {"candidate_count": 1},
        "candidate_pois": [{"name": "西湖", "type": "风景名胜"}],
        "candidate_guard": {"filtered_count": 0},
        "plan": {
            "itinerary": [{"day": 1, "theme": "西湖慢游"}],
            "estimated_total_cost": 2680,
            "cost_breakdown": {"住宿": 1200, "餐饮": 600},
        },
        "transport_plan": {"suggested_mode": "地铁", "summary": "以地铁和步行为主，减少打车折返。"},
        "lodging_recommendations": [{"name": "湖滨附近酒店"}],
        "food_recommendations": [{"name": "知味观"}],
        "review_feedback": {"passed": True},
    }


def _get_prompt(client: TestClient, name: str, session_id: str = "session-1") -> dict:
    response = client.post(
        "/mcp/travel-context",
        headers={"x-travel-context-token": "test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "prompts/get",
            "params": {"name": name, "arguments": {"session_id": session_id}},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "result" in payload
    return payload["result"]


def test_travel_context_prompts_require_real_context(monkeypatch) -> None:
    snapshot = _sample_snapshot()
    monkeypatch.setattr("backend.routers.mcp.travel_context_store.snapshot", lambda owner_id, session_id: snapshot)

    with patch.dict(os.environ, {"TRAVEL_CONTEXT_MCP_ENABLED": "1", "TRAVEL_CONTEXT_MCP_TOKEN": "test-token"}, clear=False):
        with TestClient(create_app()) as client:
            client.get("/api/system/status")
            owner_cookie = client.cookies.get(RUNTIME_OWNER_COOKIE)
            assert owner_cookie

            plan_prompt = _get_prompt(client, "plan-travel-itinerary")
            plan_text = plan_prompt["messages"][0]["content"]["text"]
            plan_payload = json.loads(plan_text)

            assert plan_payload["trip_request"]["destination"] == "杭州"
            assert "每个板块都必须结合用户实际信息和当前生成方案" in plan_payload["writing_rules"][0]
            assert "方案总览" in plan_payload["section_requirements"]
            assert "每日行程" in plan_payload["section_requirements"]

            audit_prompt = _get_prompt(client, "audit-grounding")
            audit_text = audit_prompt["messages"][0]["content"]["text"]
            audit_payload = json.loads(audit_text)

            assert audit_payload["plan"]["estimated_total_cost"] == 2680
            assert "审查时必须对照 trip_request" in audit_payload["writing_rules"][0]
            assert "交通与住宿" in audit_payload["audit_targets"]
