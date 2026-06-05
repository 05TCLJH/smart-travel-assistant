"""负责交通与住宿补充建议的代理。"""

from __future__ import annotations

from backend.agents.summary_text import summarize_transport_observation
from backend.schemas.graph_state import TripGraphState


def run_transport_lodging_agent(state: TripGraphState, runtime) -> dict:
    request_payload = state["trip_request"]
    persona = state["persona"]
    runtime.emit_progress(
        f"Transport/Lodging Agent：补充 {request_payload['destination']} 的住宿与交通建议...",
        "transport",
        step_id="transport.plan",
        status="running",
    )
    runtime.append_context_progress(state["session_id"], f"Transport/Lodging Agent：补充 {request_payload['destination']} 的住宿与交通建议...")
    lodging = runtime.local_service_tools.search_lodgings(
        request_payload["destination"],
        str(persona.get("budget_style", "舒适")),
        plan=state.get("plan") or {},
    )
    lodging, daily_stays = runtime.local_service_tools.assign_lodging_days(lodging, state["plan"], request_payload["days"])
    transport_plan = runtime.local_service_tools.build_transport_plan(
        request_payload,
        persona,
        state["plan"],
        routing_policy=state.get("routing_policy") or {},
    )
    transport_plan["daily_stays"] = daily_stays
    observation = summarize_transport_observation(transport_plan, lodging)
    runtime.emit_step("transport.plan", "done", observation)
    runtime.publish_context(state["session_id"], lodging_recommendations=lodging, transport_plan=transport_plan)
    return {
        "lodging_recommendations": lodging,
        "transport_plan": transport_plan,
        "agent_trace": list(state.get("agent_trace", []))
        + [
            {
                "agent": "transport_lodging_agent",
                "action": "build_transport_lodging_plan",
                "thought": observation,
                "observation": f"住宿候选 {len(lodging)} 条，交通建议模式 {transport_plan.get('suggested_mode', '未生成')}",
            }
        ],
    }
