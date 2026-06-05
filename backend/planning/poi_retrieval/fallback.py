"""高德不可用或候选不足时的演示/混合回退（与线上检索管道并列）。"""

from __future__ import annotations

from typing import Any, Callable

from backend.knowledge.demo_catalog import has_demo_coverage, load_demo_pois
from backend.planning.poi_retrieval.classifiers import dedupe_name_key, has_similar_poi_name
from backend.planning.search_strategy import build_search_strategy
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.knowledge.destination_catalog import merged_visit_profiles_for_destination
from backend.planning.activity_load import enrich_poi_with_activity_load
from backend.planning.poi_retrieval.priority import destination_priority_score
from backend.tools.grounding_tools import destination_conflict, is_secondary_poi, normalize_poi_tags, preferred_tags


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def required_poi_minimum(persona: dict[str, Any]) -> int:
    trip_days = max(1, _safe_int(persona.get("trip_days", 3), 3))
    return min(12, max(8, trip_days * 2 + 2))


def build_fallback_map_payload(
    destination: str,
    *,
    query_hint: str = "",
    reason: str = "",
    warning_formatter: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """完整回退地图包（is_fallback=True）。"""
    location, pois = load_demo_pois(destination, query_hint)
    r = str(reason or "").strip()
    if warning_formatter and r:
        warning = warning_formatter(r)
    else:
        warning = r or "已回退到本地演示数据。"
    if not has_demo_coverage(destination):
        warning = (
            f"{warning} 目的地「{destination}」暂无本地演示库，请配置高德 MCP 或扩展 data/demo_pois.json。"
        ).strip()
    return {
        **location,
        "pois": pois,
        "transport_hint": "当前使用本地演示景点数据，适合离线展示和答辩。",
        "provider": "demo-local-dataset",
        "is_fallback": True,
        "warning": warning,
        "search_query": f"{destination} {query_hint}".strip() if query_hint else f"{destination} 景点",
        "demo_coverage": has_demo_coverage(destination),
    }


def supplement_with_demo_pois(
    destination: str,
    persona: dict[str, Any],
    pois: list[dict[str, Any]],
    query_hint: str = "",
) -> list[dict[str, Any]]:
    """高德结果过少时，用演示库按画像偏好补全（不覆盖已有候选）。"""
    if len(pois) >= required_poi_minimum(persona):
        return pois
    if not has_demo_coverage(destination):
        return pois

    _, demo_pois = load_demo_pois(destination, query_hint)
    preferred = preferred_tags(persona)
    strategy = build_search_strategy(destination, str(persona.get("travel_style", "经典热门")))
    policy = PoiRetrievalPolicy.from_strategy(strategy)

    def demo_score(row: dict[str, Any]) -> tuple[float, float]:
        tags = normalize_poi_tags(row)
        distance = float(row.get("distance_to_destination_km", 0.0) or 0.0)
        score = len(tags & preferred) * 18.0
        score += destination_priority_score(policy, row)
        score += _safe_float(row.get("rating"), 4.5) * 8
        score -= distance * 0.9
        if distance > 20:
            score -= (distance - 20) * 1.2
        return score, -distance

    demo_pois = sorted(demo_pois, key=demo_score, reverse=True)
    visit_profiles = merged_visit_profiles_for_destination(destination)
    merged = list(pois)
    seen = {dedupe_name_key(str(item.get("name", "")).strip()) for item in merged}
    for poi in demo_pois:
        key = dedupe_name_key(str(poi.get("name", "")).strip())
        if not key or key in seen:
            continue
        enriched = dict(poi)
        if destination_conflict(enriched, destination) or is_secondary_poi(enriched):
            continue
        if has_similar_poi_name(merged, str(enriched.get("name", "")).strip()):
            continue
        enriched["provider"] = "hybrid-demo-supplement"
        enriched["source"] = "demo_poi_supplement"
        enriched = enrich_poi_with_activity_load(
            enriched, destination=destination, visit_profiles=visit_profiles
        )
        merged.append(enriched)
        seen.add(key)
        if len(merged) >= required_poi_minimum(persona):
            break
    return merged
