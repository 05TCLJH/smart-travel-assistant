"""行程组装模块。

负责把候选景点、路由能力、天气与体力策略整合成按天输出的最终行程结果。
"""

from __future__ import annotations

import math
from itertools import permutations
from collections.abc import Callable
from typing import Any

from backend.planning.activity_load import (
    build_activity_timeline,
    build_day_note,
    distribute_candidates_by_load,
    summarize_day_activity,
)
from backend.planning.candidate_scoring import rank_candidates
from backend.planning.candidate_selection import (
    cluster_candidates_by_district,
    flatten_route_points,
    select_diverse_candidates,
)
from backend.planning.day_capacity import apply_capacity_to_policy
from backend.planning.planning_profile import resolve_planning_profile
from backend.planning.stamina_profile import resolve_stamina_profile
from backend.planning.venue_schedule_policy import prepare_day_pois
from backend.planning.visit_sites import dedupe_by_scenic_cluster, seed_names_from_persona
from backend.tools.grounding_tools import itinerary_match_summary, normalize_poi_tags, strict_style_mode

_MORNING_ANCHOR_ARCHETYPES = {"museum_major", "palace_museum", "memorial_hall", "scenic_full_day", "theme_park"}
_END_ANCHOR_ROLES = {"viewpoint_after_palace"}


def _parse_lnglat(raw: str) -> tuple[float, float] | None:
    text = str(raw or "").strip()
    if "," not in text:
        return None
    try:
        lng, lat = text.split(",", 1)
        return float(lng), float(lat)
    except ValueError:
        return None


def _distance_km(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
    if not a or not b:
        return 0.0
    lng1, lat1 = a
    lng2, lat2 = b
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1 - h)))


def _is_morning_anchor(poi: dict[str, Any]) -> bool:
    return str(poi.get("pairing_role", "")).strip() == "morning_priority" or str(
        poi.get("venue_archetype", "")
    ).strip() in _MORNING_ANCHOR_ARCHETYPES


def _is_end_anchor(poi: dict[str, Any]) -> bool:
    return str(poi.get("pairing_role", "")).strip() in _END_ANCHOR_ROLES


def _route_distance(
    pois: list[dict[str, Any]],
    *,
    start_anchor: tuple[float, float] | None = None,
    end_anchor: tuple[float, float] | None = None,
) -> float:
    coords = [_parse_lnglat(str(poi.get("location", "")).strip()) for poi in pois]
    distance = 0.0
    if start_anchor and coords:
        distance += _distance_km(start_anchor, coords[0])
    for left, right in zip(coords, coords[1:]):
        distance += _distance_km(left, right)
    if end_anchor and coords:
        distance += _distance_km(coords[-1], end_anchor)
    return distance


def _optimize_segment_order(
    pois: list[dict[str, Any]],
    *,
    start_anchor: tuple[float, float] | None = None,
    end_anchor: tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    if len(pois) <= 2:
        return list(pois)
    if any(_parse_lnglat(str(poi.get("location", "")).strip()) is None for poi in pois):
        return list(pois)

    if len(pois) <= 7:
        best_order = list(pois)
        best_distance = _route_distance(best_order, start_anchor=start_anchor, end_anchor=end_anchor)
        for candidate in permutations(pois):
            candidate_list = list(candidate)
            candidate_distance = _route_distance(candidate_list, start_anchor=start_anchor, end_anchor=end_anchor)
            if candidate_distance + 0.05 < best_distance:
                best_order = candidate_list
                best_distance = candidate_distance
        return best_order

    remaining = list(pois)
    ordered: list[dict[str, Any]] = []
    cursor = start_anchor
    while remaining:
        next_index = min(
            range(len(remaining)),
            key=lambda idx: (
                _distance_km(cursor, _parse_lnglat(str(remaining[idx].get("location", "")).strip()))
                if cursor
                else idx
            ),
        )
        picked = remaining.pop(next_index)
        ordered.append(picked)
        cursor = _parse_lnglat(str(picked.get("location", "")).strip())
    return ordered


def _optimize_day_poi_order(day_pois: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(day_pois) <= 2:
        return list(day_pois)

    start_locked: list[dict[str, Any]] = []
    end_locked: list[dict[str, Any]] = []
    start_idx = 0
    end_idx = len(day_pois)

    while start_idx < len(day_pois) and _is_morning_anchor(day_pois[start_idx]):
        start_locked.append(day_pois[start_idx])
        start_idx += 1

    while end_idx > start_idx and _is_end_anchor(day_pois[end_idx - 1]):
        end_idx -= 1
        end_locked.insert(0, day_pois[end_idx])

    middle = day_pois[start_idx:end_idx]
    optimized_middle = _optimize_segment_order(
        middle,
        start_anchor=_parse_lnglat(str(start_locked[-1].get("location", "")).strip()) if start_locked else None,
        end_anchor=_parse_lnglat(str(end_locked[0].get("location", "")).strip()) if end_locked else None,
    )
    return [*start_locked, *optimized_middle, *end_locked]


def summarize_theme(destination: str, day_pois: list[dict[str, Any]]) -> str:
    """根据当日景点标签生成简短主题。"""
    tags = set()
    for poi in day_pois:
        tags.update(normalize_poi_tags(poi))
    if "history_culture" in tags:
        return f"{destination} 文化地标漫游"
    if "nature" in tags:
        return f"{destination} 自然风景漫游"
    if "city_landmark" in tags:
        return f"{destination} 城市地标漫游"
    return f"{destination} 经典漫游"


def build_timeline(day_pois: list[dict[str, Any]]) -> list[dict[str, str]]:
    """生成当天时间轴。"""
    return build_activity_timeline(day_pois)


def build_plan(
    request_payload: dict[str, Any],
    persona: dict[str, Any],
    weather: dict[str, Any],
    candidate_pois: list[dict[str, Any]],
    route_builder: Callable[[list[dict[str, Any]]], dict[str, Any]],
    static_map_builder: Callable[[dict[str, Any], list[dict[str, Any]]], str] | None = None,
    routing_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建完整的多日行程结果。"""
    rp = routing_policy or {}
    ranked = rank_candidates(candidate_pois, persona, weather if weather else {}, routing_policy=rp)
    days = int(request_payload["days"])
    is_wide_area = str(persona.get("destination_region_type", "")).strip() in {"scenic_region", "province"}
    planning_profile = resolve_planning_profile(persona, days=days, is_wide_area=is_wide_area, routing_policy=rp)
    capacity = planning_profile.capacity
    max_per_day = capacity.max_pois_cap
    daily_load_budget = capacity.daily_load_budget
    min_pois_per_day = capacity.min_pois_per_day
    profile = resolve_stamina_profile(persona)
    min_day_load_ratio = profile.min_day_load_ratio
    strict_mode = strict_style_mode(persona)
    target_slots = planning_profile.target_slots
    required_total = min(len(ranked), target_slots)

    from backend.planning.style_affinity import select_planning_pool

    pool_target = max(required_total, planning_profile.planning_pool_target)
    diverse_pool = select_planning_pool(
        ranked,
        persona,
        required_total=pool_target,
        days=days,
        strict_style=strict_mode,
    )
    if len(diverse_pool) < max(days, planning_profile.candidate_floor):
        diverse_pool = select_planning_pool(
            ranked,
            persona,
            required_total=max(pool_target, planning_profile.candidate_guardrail),
            days=days,
            strict_style=False,
        )
    required_total = min(len(diverse_pool), target_slots)
    if not diverse_pool and ranked:
        diverse_pool = ranked[: max(pool_target, planning_profile.candidate_expansion_threshold)]
        required_total = min(len(diverse_pool), target_slots)
    seeds = seed_names_from_persona(persona)
    selected = select_diverse_candidates(diverse_pool, persona, required_total, days, seed_names=seeds)
    if rp.get("prefer_cluster_by_area") and selected:
        selected = cluster_candidates_by_district(selected)
    selected = dedupe_by_scenic_cluster(selected, seed_names=seeds, max_per_cluster=1)
    supplemental_source = diverse_pool if len(diverse_pool) > len(selected) else ranked[: max(pool_target, len(selected) + days)]
    supplemental_pool = dedupe_by_scenic_cluster(
        supplemental_source,
        seed_names=seeds,
        max_per_cluster=1,
    )

    daily_buckets = distribute_candidates_by_load(
        selected,
        days,
        daily_load_budget,
        max_per_day,
        supplemental_pool=supplemental_pool,
        seed_names=seeds,
        min_pois_per_day=min_pois_per_day,
        min_day_load_ratio=min_day_load_ratio,
        min_supplement_style_affinity=planning_profile.supplement_affinity_floor,
    )
    itinerary: list[dict[str, Any]] = []
    for day_index, day_bucket in enumerate(daily_buckets, start=1):
        day_pois = dedupe_by_scenic_cluster(list(day_bucket), seed_names=seeds, max_per_cluster=1)
        day_pois = _optimize_day_poi_order(prepare_day_pois(day_pois))
        load_summary = summarize_day_activity(day_pois, daily_load_budget)
        if day_pois:
            theme = summarize_theme(request_payload["destination"], day_pois)
            day_note = build_day_note(day_pois, load_summary)
        else:
            theme = "自由活动与弹性调整"
            day_note = "为避免加入与用户偏好不贴合的地点，本日保留弹性时段，可安排特色美食、休息或预约附近博物馆。"
        itinerary.append(
            {
                "day": day_index,
                "theme": theme,
                "day_note": day_note,
                **load_summary,
                "route_points": [poi["name"] for poi in day_pois],
                "route_waypoints": [
                    {
                        "name": poi["name"],
                        "location": poi.get("location", ""),
                        "address": poi.get("address", ""),
                        "district": poi.get("adname", ""),
                        "city": poi.get("cityname", ""),
                        "type": poi.get("type", ""),
                        "type_label": poi.get("type_label", ""),
                        "rating": poi.get("rating", ""),
                        "ticket": poi.get("ticket", "未知"),
                        "cost": poi.get("cost", ""),
                        "ticket_reference_price": poi.get("ticket_reference_price"),
                        "ticket_source_type": poi.get("ticket_source_type", ""),
                        "ticket_source_label": poi.get("ticket_source_label", ""),
                        "ticket_source_name": poi.get("ticket_source_name", ""),
                        "ticket_source_url": poi.get("ticket_source_url", ""),
                        "ticket_booking_note": poi.get("ticket_booking_note", ""),
                        "ticket_last_verified_at": poi.get("ticket_last_verified_at", ""),
                        "knowledge_tags": poi.get("knowledge_tags", []),
                        "activity_load": poi.get("activity_load"),
                        "visit_hours": poi.get("visit_hours"),
                        "activity_tier_label": poi.get("activity_tier_label"),
                        "visit_site_members": poi.get("visit_site_members", []),
                        "visit_site_note": poi.get("visit_site_note", ""),
                    }
                    for poi in day_pois
                ],
                "route_geometry": (
                    route_builder(day_pois)
                    if len(day_pois) >= 2
                    else {
                        "status": "no_waypoints",
                        "message": (
                            "当日未分配景点，无路线可画。"
                            if not day_pois
                            else "当日仅 1 个景点，需至少 2 个才生成串联路线。"
                        ),
                    }
                ),
                "timeline": (
                    build_timeline(day_pois)
                    if day_pois
                    else [{"time": "10:30", "activity": "自由活动或围绕住宿点轻松漫游", "place": ""}]
                ),
            }
        )
        if static_map_builder is not None:
            itinerary[-1]["route_map_preview"] = static_map_builder(itinerary[-1]["route_geometry"], day_pois)

    return {
        "preferred_places": flatten_route_points(itinerary, seed_names=seeds) or [poi["name"] for poi in ranked[:8]],
        "itinerary": itinerary,
        "planner_provider": "langgraph-react-planner",
        "candidate_count": len(candidate_pois),
        "grounding_summary": itinerary_match_summary({"itinerary": itinerary}, persona),
        "routing_policy": apply_capacity_to_policy(rp, capacity),
    }
