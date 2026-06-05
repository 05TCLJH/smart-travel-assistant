from __future__ import annotations

from backend.agents.supervisor.agent import compose_final_result


class _RuntimeStub:
    def emit_progress(self, *args, **kwargs) -> None:
        return None

    def append_context_progress(self, *args, **kwargs) -> None:
        return None

    def emit_step(self, *args, **kwargs) -> None:
        return None

    def publish_context(self, *args, **kwargs) -> None:
        return None


def test_compose_final_result_exposes_public_persona_only() -> None:
    state = {
        "session_id": "session-1",
        "persona": {
            "name": "旅行者",
            "travel_style": "经典热门",
            "stamina": "适中",
            "budget_style": "舒适",
            "transport_preference": "打车/网约车优先",
            "likes": ["地标"],
        },
        "trip_request": {"destination": "上海", "days": 2},
        "dates": ["2026-06-10", "2026-06-11"],
        "plan": {"itinerary": []},
    }

    result = compose_final_result(state, _RuntimeStub())

    assert result["final_result"]["persona"] == {
        "name": "旅行者",
        "travel_style": "经典热门",
        "stamina": "适中",
        "budget_style": "舒适",
    }
