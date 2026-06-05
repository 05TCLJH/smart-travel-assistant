"""规划智能体，负责决定扩搜、压缩预算或生成最终行程。"""

from __future__ import annotations

from typing import Any

from backend.agents.summary_text import summarize_planner_decision
from backend.planning.planning_profile import resolve_planning_profile
from backend.planning.revision_control import record_candidate_revision
from backend.schemas.graph_state import PlannerAction, TripGraphState
from backend.planning.visit_sites import scenic_cluster_key, seed_names_from_persona
from backend.tools.budget_tools import build_budget_breakdown
from backend.tools.grounding_tools import guard_candidate_pois, strict_style_mode
from backend.tools.planning_tools import build_plan, rank_candidates


ALLOWED_ACTIONS: tuple[PlannerAction, ...] = ("expand_candidates", "trim_budget", "finalize")


def decide_planner_action(state: TripGraphState, runtime) -> dict[str, Any]:
    candidate_pois = list(state.get("candidate_pois", []) or [])
    request_payload = state["trip_request"]
    persona = state["persona"]
    review_feedback = state.get("review_feedback", {}) or {}
    planning_attempts = int(state.get("planning_attempts", 0))
    revision_state = dict(state.get("revision_state", {}) or {})
    issue_codes = {
        str(code).strip()
        for code in (review_feedback.get("issue_codes", []) or [])
        if str(code).strip()
    }

    runtime.emit_progress("Planner Agent：正在思考下一步规划动作...", "planner", step_id="planner.think", status="running")
    runtime.append_context_progress(state["session_id"], "Planner Agent：正在思考下一步规划动作...")

    action: PlannerAction = "finalize"
    query_hint = ""
    reason = "当前候选池满足要求，进入方案生成"

    min_required = resolve_planning_profile(persona, days=request_payload["days"]).candidate_expansion_threshold
    can_expand = planning_attempts < runtime.max_revisions and not revision_state.get("expansion_exhausted", False)
    can_trim_budget = planning_attempts < runtime.max_revisions and not revision_state.get("budget_trim_exhausted", False)

    if len(candidate_pois) < min_required and can_expand:
        action = "expand_candidates"
        query_hint = _hint_from_persona(persona, review_feedback)
        reason = "候选景点不足，需要补充真实景点"
    elif {"preference_mismatch", "no_valid_itinerary"} & issue_codes and can_expand:
        action = "expand_candidates"
        query_hint = _hint_from_persona(persona, review_feedback)
        reason = "当前候选与审查反馈仍不匹配，需要扩展更贴合偏好的真实景点"
    elif {"budget_exceeded"} & issue_codes and can_trim_budget:
        action = "trim_budget"
        reason = "预算审查未通过，先收紧候选池"
    elif len(candidate_pois) < min_required and not can_expand:
        reason = "候选扩展已经没有带来新增景点，直接输出当前最优方案"
    elif issue_codes and not can_expand and not can_trim_budget:
        reason = "连续修订未带来有效变化，直接输出当前最优方案"

    if planning_attempts >= runtime.max_revisions:
        action = "finalize"
        query_hint = ""
        reason = "已达到最大返工次数，直接输出当前最优方案"

    if action not in ALLOWED_ACTIONS:
        action = "finalize"
    command = {
        "thought": reason,
        "action": action,
        "query_hint": _normalize_query_hint(query_hint, persona),
    }
    runtime.emit_step("planner.think", "done", summarize_planner_decision(action, reason, command["query_hint"]))
    return {
        "planner_command": command,
        "agent_trace": list(state.get("agent_trace", []))
        + [
            {
                "agent": "planner_agent",
                "action": "reason",
                "thought": command["thought"],
                "command": action,
            }
        ],
    }


def execute_planner_action(state: TripGraphState, runtime) -> dict[str, Any]:
    command = state.get("planner_command", {}) or {}
    action = command.get("action")
    request_payload = state["trip_request"]
    persona = state["persona"]
    candidate_pois = list(state.get("candidate_pois", []) or [])
    weather = state.get("weather", {}) or {}
    revision_state = dict(state.get("revision_state", {}) or {})

    if action == "expand_candidates":
        raw_query_hint = str(command.get("query_hint", "")).strip()
        generic_hints = {
            "热门景点",
            "必去景点",
            "景点",
            "必去",
            "城市地标",
            "经典景点",
            "经典线路",
            "推荐",
            "旅行风格",
            "默认",
        }
        query_hint = raw_query_hint or _hint_from_persona(persona, state.get("review_feedback", {}))
        if query_hint in generic_hints:
            planner_hint = str(persona.get("planner_query_hint", "")).strip()
            query_hint = planner_hint or _hint_from_persona(persona, state.get("review_feedback", {}))
        runtime.emit_progress(
            f"Planner Agent：候选不足，正在扩展检索词“{query_hint or '热门景点'}”...",
            "planner",
            step_id="planner.expand",
            status="running",
        )
        runtime.append_context_progress(state["session_id"], f"Planner Agent：候选不足，正在扩展检索词“{query_hint or '热门景点'}”...")
        extra = runtime.research_tools.search_candidate_pois(request_payload["destination"], persona, query_hint or "热门景点")
        merged = _merge_pois(candidate_pois, extra)
        filtered, candidate_guard = guard_candidate_pois(merged, request_payload, persona, weather)
        next_revision_state, delta = record_candidate_revision(revision_state, "expand_candidates", candidate_pois, filtered)
        detail = (
            f"扩展后新增 {delta['added_count']} 个候选，当前保留 {len(filtered)} 个景点"
            if delta["changed"]
            else f"扩展未带来新候选，当前仍保留 {len(filtered)} 个景点"
        )
        runtime.emit_step("planner.expand", "done", detail)
        runtime.publish_context(
            state["session_id"],
            candidate_pois=filtered,
            candidate_guard=candidate_guard,
            revision_state=next_revision_state,
        )
        return {
            "candidate_pois": filtered,
            "candidate_guard": candidate_guard,
            "planning_attempts": int(state.get("planning_attempts", 0)) + 1,
            "revision_state": next_revision_state,
            "agent_trace": list(state.get("agent_trace", []))
            + [
                {
                    "agent": "planner_agent",
                    "action": "expand_candidates",
                    "query_hint": query_hint,
                    "observation": detail,
                }
            ],
        }

    if action == "trim_budget":
        runtime.emit_progress(
            "Planner Agent：正在根据预算、天气和贴合度收缩候选范围...",
            "planner",
            step_id="planner.trim",
            status="running",
        )
        runtime.append_context_progress(state["session_id"], "Planner Agent：正在根据预算、天气和贴合度收缩候选范围...")
        ranked = rank_candidates(candidate_pois, persona, weather, routing_policy=state.get("routing_policy") or {})
        trimmed = [poi for poi in ranked if _poi_budget_friendly(poi)]
        min_required = resolve_planning_profile(persona, days=request_payload["days"]).candidate_expansion_threshold
        if len(trimmed) < min_required and not strict_style_mode(persona):
            trimmed = ranked[:min_required]
        filtered, candidate_guard = guard_candidate_pois(trimmed, request_payload, persona, weather)
        next_revision_state, delta = record_candidate_revision(revision_state, "trim_budget", candidate_pois, filtered)
        detail = (
            f"收缩后调整了候选池，当前保留 {len(filtered)} 个景点"
            if delta["changed"]
            else f"预算收缩未改变候选池，当前仍保留 {len(filtered)} 个景点"
        )
        runtime.emit_step("planner.trim", "done", detail)
        runtime.publish_context(
            state["session_id"],
            candidate_pois=filtered,
            candidate_guard=candidate_guard,
            revision_state=next_revision_state,
        )
        return {
            "candidate_pois": filtered,
            "candidate_guard": candidate_guard,
            "planning_attempts": int(state.get("planning_attempts", 0)) + 1,
            "revision_state": next_revision_state,
            "agent_trace": list(state.get("agent_trace", []))
            + [
                {
                    "agent": "planner_agent",
                    "action": "trim_budget",
                    "observation": detail,
                }
            ],
        }

    return {}


def finalize_plan(state: TripGraphState, runtime) -> dict[str, Any]:
    runtime.emit_progress("Planner Agent：正在生成最终行程草案...", "planner", step_id="planner.finalize", status="running")
    runtime.append_context_progress(state["session_id"], "Planner Agent：正在生成最终行程草案...")
    runtime.emit_step("planner.cluster_layout", "running", "按景区簇去重并排期，确保每个景区仅出现一次")
    map_data = dict(state.get("map_data", {}) or {})
    candidate_pois = list(state.get("candidate_pois", []) or map_data.get("pois", []) or [])
    candidate_pois, candidate_guard = guard_candidate_pois(candidate_pois, state["trip_request"], state["persona"], state.get("weather", {}) or {})
    def route_builder(day_pois: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "status": "poi_markers_only" if day_pois else "no_waypoints",
            "provider": "marker-preview",
            "route_profile": "none",
            "effective_mode": "none",
            "distance_m": 0,
            "duration_s": 0,
            "polyline": [],
            "steps": [],
            "draw_path": False,
            "message": "仅展示当日景点分布，不再规划景点之间的路线" if day_pois else "当日未分配景点",
        }

    routing_policy = dict(state.get("routing_policy") or {})

    plan = build_plan(
        state["trip_request"],
        state["persona"],
        state.get("weather", {}) or {},
        candidate_pois,
        route_builder,
        runtime.research_tools.build_static_map_preview,
        routing_policy=routing_policy,
    )
    plan.update(build_budget_breakdown(state["trip_request"], state["persona"], plan.get("itinerary", []) or []))
    plan["candidate_guard"] = candidate_guard or state.get("candidate_guard", {})
    if not any(day.get("route_points") for day in plan.get("itinerary", [])):
        plan["planner_warning"] = "候选景点不足，当前未生成有效路线"

    seeds = seed_names_from_persona(state["persona"])
    trip_clusters: set[str] = set()
    for day in plan.get("itinerary", []) or []:
        for name in day.get("route_points", []) or []:
            cluster = scenic_cluster_key(str(name), seeds)
            if cluster:
                trip_clusters.add(cluster)
    daily_budget = int(routing_policy.get("daily_activity_load_budget") or 100)
    load_days = [
        f"D{d.get('day', '?')} {d.get('activity_load_used', '?')}/{daily_budget}"
        for d in plan.get("itinerary", []) or []
        if d.get("route_points")
    ]
    runtime.emit_step(
        "planner.cluster_layout",
        "done",
        f"按活动负荷装箱：全程 {len(trip_clusters)} 个景区簇；"
        + ("每日负荷 " + "；".join(load_days[:5]) if load_days else "暂无有效排期"),
    )
    runtime.emit_step(
        "planner.finalize",
        "done",
        f"行程草案已生成（{len(plan.get('itinerary', []) or [])} 天 / 预计 ￥{plan.get('estimated_total_cost', 0):.0f}）",
    )
    runtime.publish_context(state["session_id"], plan=plan, candidate_pois=candidate_pois, candidate_guard=candidate_guard)
    return {"plan": plan, "candidate_pois": candidate_pois, "candidate_guard": candidate_guard}


def planner_next_step(state: TripGraphState) -> str:
    return str((state.get("planner_command") or {}).get("action") or "finalize")


def _hint_from_persona(persona: dict[str, Any], review_feedback: dict[str, Any]) -> str:
    travel_style = str(persona.get("travel_style", ""))
    if "小众" in travel_style or "探索" in travel_style:
        return "小众景点 本地人爱去 老街 步道"
    if "自然" in travel_style:
        return "自然风景"
    if "文化" in travel_style or "历史" in travel_style:
        return "历史文化"
    if "休闲" in travel_style or "度假" in travel_style:
        return "公园 街区 夜景 慢游"
    planner_hint = str(persona.get("planner_query_hint", "")).strip()
    if planner_hint:
        return planner_hint
    hotspots = persona.get("destination_hotspots") or []
    if hotspots:
        return " ".join(str(item) for item in hotspots[:4])
    if any("预算" in issue for issue in review_feedback.get("issues", [])):
        return "免费 公园 博物馆"
    return "热门景点"


def _normalize_query_hint(raw_hint: str, persona: dict[str, Any]) -> str:
    hint = str(raw_hint or "").strip()
    if not hint:
        return _hint_from_persona(persona, {})
    if len(hint) > 24:
        return _hint_from_persona(persona, {})
    if any(token in hint for token in ("请", "推荐", "用户", "景点。", "兴趣", "旅行风格")):
        return _hint_from_persona(persona, {})
    return hint


def _merge_pois(existing: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for poi in [*existing, *extra]:
        name = str(poi.get("name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        merged.append(poi)
    return merged


def _poi_budget_friendly(poi: dict[str, Any]) -> bool:
    ticket = str(poi.get("ticket", poi.get("cost", ""))).strip()
    if ticket in {"", "未知", "免费"}:
        return True
    try:
        return float(ticket) <= 60
    except ValueError:
        return True
