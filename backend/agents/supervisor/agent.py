"""负责路由决策与最终回复组装的总控代理。"""

from __future__ import annotations

from backend.agents.summary_text import summarize_supervisor_decision
from backend.core.public_views import sanitize_trip_result
from backend.planning.revision_control import record_review_cycle
from backend.schemas.graph_state import TripGraphState


def decide_supervisor_route(state: TripGraphState, runtime) -> dict:
    review_feedback = state.get("review_feedback", {}) or {}
    planning_attempts = int(state.get("planning_attempts", 0))
    revision_state = record_review_cycle(state.get("revision_state", {}) or {}, review_feedback, state.get("plan") or {})
    has_research_context = bool(state.get("weather")) or bool(state.get("map_data"))
    runtime.emit_step("supervisor.review", "running", "评估方案是否通过审查")

    forced_finalize_reason = ""
    if review_feedback.get("passed"):
        next_step = "finalize"
    elif revision_state.get("stagnant_reviews", 0) >= 1:
        next_step = "finalize"
        forced_finalize_reason = "连续两轮审查结论完全一致且方案未变化，停止空转并输出当前最优结果"
    elif planning_attempts >= runtime.max_revisions:
        next_step = "finalize"
    elif not has_research_context:
        next_step = "research"
    else:
        next_step = str(review_feedback.get("routing_hint", "planning") or "planning")
        if next_step not in {"planning", "finalize"}:
            next_step = "planning"
        if review_feedback.get("issue_codes") and revision_state.get("expansion_exhausted") and revision_state.get("budget_trim_exhausted"):
            next_step = "finalize"
            forced_finalize_reason = "候选扩展与预算收缩都未再带来变化，停止重复规划并输出当前最优结果"

    merged_feedback = {
        **review_feedback,
        "next_step": next_step,
        "forced_finalize": bool(forced_finalize_reason),
    }
    if forced_finalize_reason:
        merged_feedback["forced_finalize_reason"] = forced_finalize_reason

    summary = summarize_supervisor_decision(next_step, merged_feedback, planning_attempts, runtime.max_revisions)
    runtime.emit_step("supervisor.review", "done", summary)
    if next_step != "finalize":
        runtime.emit_step("supervisor.reroute", "done", summary)
    runtime.append_context_progress(state["session_id"], f"Supervisor Agent：{summary}")
    runtime.publish_context(state["session_id"], review_feedback=merged_feedback, revision_state=revision_state)
    return {
        "review_feedback": merged_feedback,
        "revision_state": revision_state,
        "agent_trace": list(state.get("agent_trace", []))
        + [{"agent": "supervisor_agent", "action": "route", "thought": summary, "observation": summary, "next_step": next_step}],
    }


def supervisor_next_step(state: TripGraphState) -> str:
    return str((state.get("review_feedback") or {}).get("next_step") or "finalize")


def compose_final_result(state: TripGraphState, runtime) -> dict:
    runtime.emit_progress(
        "Supervisor Agent：正在整理最终结果...",
        "supervisor",
        step_id="supervisor.finalize",
        status="running",
    )
    runtime.append_context_progress(state["session_id"], "Supervisor Agent：正在整理最终结果...")
    final_result = sanitize_trip_result({
        "session_id": state["session_id"],
        "persona": state["persona"],
        "trip_request": state["trip_request"],
        "dates": state["dates"],
        "weather": state.get("weather", {}) or {},
        "map_data": state.get("map_data", {}) or {},
        "food_recommendations": state.get("food_recommendations", []) or [],
        "lodging_recommendations": state.get("lodging_recommendations", []) or [],
        "transport_plan": state.get("transport_plan", {}) or {},
        "routing_policy": state.get("routing_policy") or {},
        "plan": state["plan"],
        "reflection": state.get("reflection", {}) or {},
        "planning_attempts": int(state.get("planning_attempts", 0)),
        "tips": state.get("tips", {"tips": []}),
    })
    runtime.emit_step(
        "supervisor.finalize",
        "done",
        f"最终结果已整理完成，输出 {len(final_result['plan'].get('itinerary', []) or [])} 天行程",
    )
    runtime.publish_context(state["session_id"], final_result=final_result, status="finalizing")
    return {"final_result": final_result}
