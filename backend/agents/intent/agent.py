"""行程规划流程中的结构化需求理解代理。"""

from __future__ import annotations

from backend.agents.llm_utils import invoke_structured_json
from backend.agents.summary_text import summarize_intent_focus
from backend.schemas.graph_state import TripGraphState
from backend.tools.routing_policy import INTENT_ROUTING_SYSTEM_PROMPT, merge_routing_policy


def run_intent_agent(state: TripGraphState, runtime) -> dict:
    runtime.emit_progress("Intent Agent：正在解析用户需求...", "intent", step_id="intent.parse", status="running")
    runtime.append_context_progress(state["session_id"], "Intent Agent：正在解析用户需求...")
    request_payload = runtime.research_tools.normalize_request(state.get("trip_request", {}))
    persona = runtime.persona_service.enrich(state.get("persona") or {}, trip_request=request_payload)
    dates = runtime.research_tools.build_dates(request_payload["start_date"], request_payload["days"])
    runtime.emit_step(
        "intent.parse",
        "done",
        f"已解析 {request_payload['destination']} {request_payload['days']} 天 / 预算 {request_payload['budget']:.0f}",
    )

    weather_preview = (state.get("weather") or {}).get("rating") if state.get("weather") else ""
    llm_policy_raw = invoke_structured_json(
        runtime,
        INTENT_ROUTING_SYSTEM_PROMPT,
        {
            "trip_request": request_payload,
            "persona": {
                "travel_style": persona.get("travel_style"),
                "stamina": persona.get("stamina"),
                "budget_style": persona.get("budget_style"),
                "transport_preference": persona.get("transport_preference"),
                "likes": persona.get("likes", []),
                "must_have": persona.get("must_have", []),
                "max_pois_per_day": persona.get("max_pois_per_day"),
            },
            "weather_rating": weather_preview or None,
        },
        fallback={},
    )
    routing_policy = merge_routing_policy(llm_policy_raw if isinstance(llm_policy_raw, dict) else {}, persona, request_payload)
    llm_focus = summarize_intent_focus(request_payload, persona, routing_policy)
    runtime.emit_progress(
        (
            "Intent Agent：已生成出行策略"
            f"（单日负荷上限 {routing_policy.get('daily_activity_load_budget')} / "
            f"景点数上限 {routing_policy.get('max_pois_per_day')} / "
            f"{routing_policy.get('route_profile')} / {routing_policy.get('day_pacing')}）"
        ),
        "intent",
        step_id="intent.policy",
        status="done",
    )
    runtime.publish_context(
        state["session_id"],
        trip_request=request_payload,
        persona=persona,
        dates=dates,
        routing_policy=routing_policy,
        intent={"task_type": "trip_plan", "scene": "travel_planning", "llm_focus": llm_focus, "routing_policy": routing_policy},
    )

    return {
        "routing_policy": routing_policy,
        "intent": {
            "task_type": "trip_plan",
            "scene": "travel_planning",
            "destination": request_payload["destination"],
            "days": request_payload["days"],
            "budget": request_payload["budget"],
            "llm_focus": llm_focus,
            "routing_policy": routing_policy,
        },
        "trip_request": request_payload,
        "persona": persona,
        "dates": dates,
        "planning_attempts": state.get("planning_attempts", 0),
        "progress_events": list(state.get("progress_events", [])),
        "agent_trace": list(state.get("agent_trace", []))
        + [
            {
                "agent": "intent_agent",
                "action": "understand_request",
                "thought": llm_focus,
                "observation": f"routing_policy={routing_policy.get('day_pacing')}/{routing_policy.get('route_profile')}/max{routing_policy.get('max_pois_per_day')}",
            }
        ],
        "errors": list(state.get("errors", [])),
    }
