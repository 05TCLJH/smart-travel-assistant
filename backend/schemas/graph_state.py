"""旅行规划工作流共享图状态。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


TaskType = Literal["trip_plan", "modify_plan", "vision", "qa"]
PlannerAction = Literal["expand_candidates", "trim_budget", "finalize"]


class TripGraphState(TypedDict, total=False):
    session_id: str
    thread_id: str
    user_query: str
    intent: dict[str, Any]
    routing_policy: dict[str, Any]
    trip_request: dict[str, Any]
    persona: dict[str, Any]
    dates: list[str]
    weather: dict[str, Any]
    map_data: dict[str, Any]
    candidate_pois: list[dict[str, Any]]
    candidate_guard: dict[str, Any]
    research_brief: dict[str, Any]
    food_recommendations: list[dict[str, Any]]
    lodging_recommendations: list[dict[str, Any]]
    transport_plan: dict[str, Any]
    planner_command: dict[str, Any]
    plan: dict[str, Any]
    review_feedback: dict[str, Any]
    reflection: dict[str, Any]
    tips: dict[str, Any]
    final_result: dict[str, Any]
    planning_attempts: int
    revision_state: dict[str, Any]
    progress_events: list[str]
    agent_trace: list[dict[str, Any]]
    errors: list[str]
