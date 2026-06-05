"""基于本地检索结果的美食推荐代理。"""

from __future__ import annotations

from backend.agents.summary_text import summarize_food_observation
from backend.schemas.graph_state import TripGraphState


def run_food_agent(state: TripGraphState, runtime) -> dict:
    request_payload = state["trip_request"]
    runtime.emit_progress(
        f"Food Agent：检索 {request_payload['destination']} 的当地特色美食...",
        "food",
        step_id="food.search",
        status="running",
    )
    runtime.append_context_progress(state["session_id"], f"Food Agent：检索 {request_payload['destination']} 的当地特色美食...")
    foods = runtime.local_service_tools.search_local_foods(request_payload["destination"], state["persona"])
    observation = summarize_food_observation(foods, request_payload["destination"])
    runtime.emit_step("food.search", "done", observation)
    runtime.publish_context(state["session_id"], food_recommendations=foods)
    return {
        "food_recommendations": foods,
        "agent_trace": list(state.get("agent_trace", []))
        + [
            {
                "agent": "food_agent",
                "action": "search_local_foods",
                "thought": observation,
                "observation": f"找到 {len(foods)} 条当地美食结果",
            }
        ],
    }
