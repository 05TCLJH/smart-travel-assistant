"""候选景点筛选模块。

负责候选去冗余、风格多样性控制、按天分配兼容接口，以及路线点位扁平化输出。
"""

from __future__ import annotations

from typing import Any

from backend.planning import style_profile
from backend.planning.activity_load import distribute_candidates_by_load
from backend.planning.visit_sites import (
    cluster_key_for_poi,
    dedupe_by_scenic_cluster,
    scenic_cluster_key,
    seed_names_from_persona,
)
from backend.tools.grounding_tools import normalize_poi_tags, preferred_tags


def candidate_family(poi: dict[str, Any]) -> str:
    """将景点归并到统一候选类别，便于做多样性控制。"""
    name = str(poi.get("name", "")).strip()
    tags = set(poi.get("canonical_tags", []) or normalize_poi_tags(poi))
    if "故居" in name or "旧居" in name:
        return "residence"
    if "city_landmark" in tags:
        return "landmark"
    if "museum" in tags:
        return "museum"
    if "street" in tags:
        return "street"
    if "history_culture" in tags:
        return "culture"
    if "nature" in tags:
        return "nature"
    return "general"


def candidate_priority(poi: dict[str, Any]) -> tuple[int, float, float, float]:
    """统一候选优先级，避免去重后丢失风格亲和度排序。"""

    return (
        1 if poi.get("preference_hit") else 0,
        float(poi.get("style_affinity", 0.0) or 0.0),
        float(poi.get("suitability_score", 0.0) or 0.0),
        float(poi.get("constraint_score", 0.0) or 0.0),
    )


def select_diverse_candidates(
    ranked: list[dict[str, Any]],
    persona: dict[str, Any],
    required_total: int,
    days: int,
    *,
    seed_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """按类别与簇约束选择候选池，避免同类景点过多或同景区重复。"""
    if required_total <= 0:
        return []

    seeds = seed_names or seed_names_from_persona(persona)
    ranked_unique = dedupe_by_scenic_cluster(ranked, seed_names=seeds, max_per_cluster=1)
    ranked_unique = sorted(ranked_unique, key=candidate_priority, reverse=True)

    preferred = preferred_tags(persona)
    family_buckets: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in ("landmark", "museum", "culture", "street", "nature", "residence", "general")
    }
    for poi in ranked_unique:
        family_buckets.setdefault(candidate_family(poi), []).append(poi)
    for bucket in family_buckets.values():
        bucket.sort(key=candidate_priority, reverse=True)

    museum_cap = required_total
    if preferred & {"history_culture", "museum"}:
        museum_cap = (
            max(2, min(required_total - 1, (required_total + 1) // 2))
            if required_total > 2
            else required_total
        )
    if style_profile.is_offbeat_style(persona):
        museum_cap = min(museum_cap, max(1, required_total // 3 or 1))
    residence_cap = 1 if style_profile.is_classic_style(persona) else required_total
    landmark_goal = 0
    if "city_landmark" in preferred:
        landmark_goal = min(max(1, days), max(1, required_total // 2))
    if style_profile.is_offbeat_style(persona):
        landmark_goal = 0

    ordered_families: list[str] = []
    if style_profile.is_offbeat_style(persona):
        ordered_families.extend(["street", "culture", "nature", "museum", "general", "landmark", "residence"])
    elif preferred & {"history_culture", "museum"}:
        ordered_families.extend(["landmark", "culture", "museum", "street", "nature", "residence", "general"])
    elif "nature" in preferred:
        ordered_families.extend(["nature", "landmark", "culture", "street", "museum", "residence", "general"])
    else:
        ordered_families.extend(["landmark", "culture", "museum", "nature", "street", "residence", "general"])

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_clusters: set[str] = set()
    family_counts = {name: 0 for name in family_buckets}

    def add_poi(poi: dict[str, Any]) -> bool:
        poi_key = str(poi.get("poi_id") or poi.get("name") or "").strip()
        cluster = cluster_key_for_poi(poi, seeds)
        if not poi_key or poi_key in seen_ids or len(selected) >= required_total:
            return False
        if cluster and cluster in seen_clusters:
            return False
        family = candidate_family(poi)
        if family == "museum" and family_counts["museum"] >= museum_cap:
            return False
        if family == "residence" and family_counts["residence"] >= residence_cap:
            return False
        seen_ids.add(poi_key)
        if cluster:
            seen_clusters.add(cluster)
        selected.append(poi)
        family_counts[family] = family_counts.get(family, 0) + 1
        return True

    for poi in family_buckets.get("landmark", []):
        if family_counts["landmark"] >= landmark_goal:
            break
        add_poi(poi)

    for family in ordered_families:
        bucket = family_buckets.get(family, [])
        if bucket:
            add_poi(bucket[0])

    cursor_by_family = {family: 0 for family in ordered_families}
    while len(selected) < required_total:
        progressed = False
        for family in ordered_families:
            bucket = family_buckets.get(family, [])
            cursor = cursor_by_family.get(family, 0)
            while cursor < len(bucket):
                poi = bucket[cursor]
                cursor += 1
                if add_poi(poi):
                    progressed = True
                    break
            cursor_by_family[family] = cursor
            if len(selected) >= required_total:
                break
        if not progressed:
            break

    if len(selected) < required_total:
        for poi in ranked_unique:
            add_poi(poi)
            if len(selected) >= required_total:
                break
    return sorted(selected, key=candidate_priority, reverse=True)


def cluster_candidates_by_district(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按日切分前将同区候选相邻排列，减少跨区折返。"""

    def district_key(poi: dict[str, Any]) -> str:
        return str(poi.get("district") or poi.get("adname") or poi.get("city") or "").strip()

    return sorted(
        selected,
        key=lambda poi: (district_key(poi), -float(poi.get("suitability_score", 0.0) or 0.0)),
    )


def distribute_candidates(
    selected: list[dict[str, Any]],
    days: int,
    max_per_day: int,
    *,
    seed_names: set[str] | None = None,
    daily_load_budget: int = 100,
) -> list[list[dict[str, Any]]]:
    """兼容旧调用入口，内部统一走活动负荷分配。"""
    return distribute_candidates_by_load(
        selected,
        days,
        daily_load_budget,
        max_per_day,
        seed_names=seed_names,
    )


def flatten_route_points(
    itinerary: list[dict[str, Any]],
    limit: int = 8,
    *,
    seed_names: set[str] | None = None,
) -> list[str]:
    """提取行程中去重后的核心路线点名称。"""
    points: list[str] = []
    seen_clusters: set[str] = set()
    for day in itinerary:
        for name in day.get("route_points", []):
            text = str(name or "").strip()
            if not text:
                continue
            cluster = scenic_cluster_key(text, seed_names) if seed_names else text
            if cluster in seen_clusters:
                continue
            if cluster:
                seen_clusters.add(cluster)
            points.append(text)
            if len(points) >= limit:
                return points
    return points
