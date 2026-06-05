"""预算与可执行性审查代理。"""

from __future__ import annotations

from backend.agents.summary_text import summarize_budget_observation
from backend.schemas.graph_state import TripGraphState
from backend.tools.budget_tools import build_reflection, build_tips, review_plan


def run_budget_reviewer_agent(state: TripGraphState, runtime) -> dict:
    runtime.emit_progress(
        "Budget Reviewer Agent：正在检查预算、天气与可执行性...",
        "budget",
        step_id="budget.review",
        status="running",
    )
    runtime.append_context_progress(state["session_id"], "Budget Reviewer Agent：正在检查预算、天气与可执行性...")
    review_feedback = review_plan(state["trip_request"], state["persona"], state.get("weather", {}) or {}, state["plan"])
    observation = summarize_budget_observation(review_feedback)
    runtime.emit_step("budget.review", "done", observation)
    reflection = build_reflection(state["plan"], review_feedback)
    tips = {
        "tips": build_tips(
            state.get("weather", {}) or {},
            state["plan"],
            state["trip_request"],
            state["persona"],
            state.get("transport_plan", {}) or {},
            state.get("lodging_recommendations", []) or [],
        )
    }
    runtime.publish_context(state["session_id"], review_feedback=review_feedback, reflection=reflection, tips=tips)
    return {
        "review_feedback": review_feedback,
        "reflection": reflection,
        "tips": tips,
        "agent_trace": list(state.get("agent_trace", []))
        + [
            {
                "agent": "budget_reviewer_agent",
                "action": "review_plan",
                "thought": observation,
                "observation": review_feedback.get("summary", ""),
                "issues": review_feedback.get("issues", []),
            }
        ],
    }
