"""用于进度播报与执行轨迹输出的稳定摘要文案。"""

from __future__ import annotations

from typing import Any


def summarize_intent_focus(request_payload: dict[str, Any], persona: dict[str, Any], routing_policy: dict[str, Any]) -> str:
    destination = str(request_payload.get("destination", "目的地")).strip() or "目的地"
    days = int(request_payload.get("days", 0) or 0)
    style = str(persona.get("travel_style", "当前风格")).strip() or "当前风格"
    pacing = str(routing_policy.get("day_pacing", "")).strip()
    if pacing:
        return f"{destination}{days}天行程，优先满足{style}，节奏{pacing}"
    return f"{destination}{days}天行程，优先满足{style}与预算约束"


def summarize_research_observation(
    candidate_pois: list[dict[str, Any]],
    weather: dict[str, Any],
    candidate_guard: dict[str, Any],
    persona: dict[str, Any],
) -> str:
    count = len(candidate_pois)
    weather_rating = str(weather.get("rating", "未知")).strip() or "未知"
    filtered = int(candidate_guard.get("filtered_count", 0) or 0)
    style = str(persona.get("travel_style", "")).strip()
    if count <= 4:
        return f"候选仅 {count} 个，天气{weather_rating}，建议继续扩充更贴合{style or '偏好'}的景点"
    if filtered > 0:
        return f"候选池保留 {count} 个，已按天气与约束过滤 {filtered} 个"
    return f"候选池已有 {count} 个景点，天气{weather_rating}，足以进入排期"


def summarize_food_observation(foods: list[dict[str, Any]], destination: str) -> str:
    count = len(foods)
    if count == 0:
        return f"{destination} 暂无稳定餐饮候选，建议现场补充"
    top = str((foods[0] or {}).get("name", "")).strip()
    if top:
        return f"已找到 {count} 条当地美食，优先保留 {top} 等代表性餐饮"
    return f"已找到 {count} 条当地美食候选"


def summarize_transport_observation(transport_plan: dict[str, Any], lodgings: list[dict[str, Any]]) -> str:
    mode = str(transport_plan.get("suggested_mode", "默认交通方式")).strip() or "默认交通方式"
    if not transport_plan.get("route_planning_enabled", True):
        return f"住宿候选 {len(lodgings)} 家，已生成景点地图与入住建议，景点间导航请结合地图 App 实时查看"
    approx = "，里程为估算值" if transport_plan.get("is_approximate") else ""
    return f"住宿候选 {len(lodgings)} 家，建议以{mode}为主{approx}"


def summarize_budget_observation(review_feedback: dict[str, Any]) -> str:
    summary = str(review_feedback.get("summary", "")).strip()
    if summary:
        return summary
    issues = list(review_feedback.get("issues", []) or [])
    if issues:
        return f"共发现 {len(issues)} 个预算或可执行性风险"
    return "预算与可执行性检查通过"


def summarize_planner_decision(action: str, reason: str, query_hint: str = "") -> str:
    if action == "expand_candidates":
        return f"{reason} 扩展检索词：{query_hint or '热门景点'}"
    if action == "trim_budget":
        return reason or "根据预算和天气收缩候选池"
    return reason or "当前候选足以生成最终行程"


def summarize_supervisor_decision(next_step: str, review_feedback: dict[str, Any], planning_attempts: int, max_revisions: int) -> str:
    forced_reason = str(review_feedback.get("forced_finalize_reason", "")).strip()
    if forced_reason:
        return forced_reason
    if review_feedback.get("passed"):
        return "方案通过审查，准备整理最终输出"
    if planning_attempts >= max_revisions:
        return "已达到最大返工次数，保留当前最优结果输出"
    if next_step == "research":
        return "候选事实仍不足，回到调研阶段补充真实景点"
    if next_step == "planning":
        return "方案未通过审查，回到规划阶段收缩或重排"
    return "方案可以输出"
