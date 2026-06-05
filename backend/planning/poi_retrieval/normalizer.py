"""景点归一化：坐标、距离、过滤管道、去重与排序。"""

from __future__ import annotations

from typing import Any

from backend.planning.poi_retrieval.classifiers import (
    dedupe_name_key,
    guess_tags,
    is_complex_sub_poi,
    is_food_poi_type,
    is_usable_raw_poi,
)
from backend.planning.poi_retrieval.coordinate import CoordinateResolver
from backend.planning.poi_retrieval.filters import FilterContext, NormalizedPoiDraft, apply_filter_chain
from backend.planning.poi_retrieval.geo import distance_km, parse_lnglat
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.planning.poi_retrieval.priority import destination_priority_score
from backend.knowledge.destination_catalog import merged_visit_profiles_for_destination
from backend.planning.activity_load import enrich_poi_with_activity_load
from backend.planning.destination_constraints import resolve_constraint_profile
from backend.planning.poi_roles import attach_poi_role
from backend.planning.visit_sites import dedupe_by_scenic_cluster
from backend.tools.grounding_tools import normalize_admin_name, normalize_poi_tags, preferred_tags
from backend.tools.ticket_price_resolver import attach_ticket_reference


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pick_primary_city(pois: list[dict[str, Any]]) -> str:
    city_scores: dict[str, tuple[float, int]] = {}
    for poi in pois:
        city = str(poi.get("city", "")).strip() or str(poi.get("district", "")).strip()
        city_key = normalize_admin_name(city)
        if not city_key:
            continue
        score, count = city_scores.get(city_key, (0.0, 0))
        score += float(poi.get("popularity_score", 0.0) or 0.0)
        count += 1
        city_scores[city_key] = (score, count)
    if not city_scores:
        return ""
    return max(city_scores.items(), key=lambda item: (item[1][1], item[1][0]))[0]


def restrict_to_primary_city_cluster(pois: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary_city = pick_primary_city(pois)
    if not primary_city:
        return pois
    clustered = [
        poi
        for poi in pois
        if normalize_admin_name(poi.get("city", "")) == primary_city
        or normalize_admin_name(poi.get("district", "")) == primary_city
    ]
    if len(clustered) >= max(6, min(10, len(pois))):
        return clustered
    return clustered or pois


def normalize_pois(
    rows: list[Any],
    origin_location: str,
    destination: str,
    persona: dict[str, Any],
    scope: dict[str, Any] | None,
    policy: PoiRetrievalPolicy,
    coords: CoordinateResolver,
) -> list[dict[str, Any]]:
    pois_by_key: dict[str, dict[str, Any]] = {}
    origin_pair = parse_lnglat(origin_location)
    preferred = preferred_tags(persona)
    niche_mode = policy.style_key == "offbeat"
    filter_ctx = FilterContext(
        destination=destination,
        policy=policy,
        scope=scope or {},
        persona=persona,
        preferred_tags=preferred,
        niche_mode=niche_mode,
        constraint_profile=resolve_constraint_profile(destination, persona, scope or {}),
    )
    scope_province = str((scope or {}).get("province", "")).strip()
    scope_is_province_level = bool((scope or {}).get("is_province_level"))

    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        if not name or not is_usable_raw_poi(row):
            continue

        lnglat = str(row.get("location", "")).strip()
        address = str(row.get("address", "")).strip()
        # 大多数记录沿用前置采集坐标；仅在缺坐标或命中高风险质心时才重解，避免不必要的慢查询。
        if not lnglat or coords.should_resolve_search_coordinate(row, name, address):
            lnglat = coords.resolve_poi_coordinate(row, None, destination)
        if not lnglat:
            continue

        poi_pair = parse_lnglat(lnglat)
        if not poi_pair:
            continue
        dist = distance_km(origin_pair, poi_pair)
        radius_cap = float(policy.search_radius_km)
        if bool(row.get("_knowledge_seed")):
            radius_cap = max(radius_cap, 120.0)
        if dist > radius_cap:
            continue

        type_text = str(row.get("type", row.get("typecode", "")))
        if is_food_poi_type(type_text) or is_complex_sub_poi(name, type_text):
            continue

        cost = str((row.get("biz_ext") or {}).get("cost", "")).strip()
        province_text = str(row.get("pname", "")).strip()
        if scope_is_province_level and not province_text and str(row.get("cityname", "")).strip():
            province_text = scope_province

        poi = attach_poi_role({
            "name": name,
            "type": type_text,
            "ticket": cost or "未知",
            "cost": cost,
            "provider": "amap-mcp",
            "address": address,
            "province": province_text,
            "city": str(row.get("cityname", "")),
            "district": str(row.get("adname", "")),
            "poi_id": str(row.get("id", "")),
            "photo": str(row.get("photo", "")),
            "location": lnglat,
            "rating": str((row.get("biz_ext") or {}).get("rating", "")),
            "distance_to_destination_km": round(dist, 1),
            "knowledge_hit": True,
            "knowledge_tags": guess_tags(name, type_text),
            "source": "amap_mcp_poi_search",
            "knowledge_seed": bool(row.get("_knowledge_seed")),
        })
        poi = attach_ticket_reference(poi, destination)
        tags = normalize_poi_tags(poi)
        draft = NormalizedPoiDraft(
            name=name,
            type_text=type_text,
            poi=poi,
            tags=tags,
            distance_km=dist,
            knowledge_seed=bool(poi.get("knowledge_seed")),
        )
        if not apply_filter_chain(filter_ctx, draft):
            continue

        poi["popularity_score"] = round(
            _safe_float(poi["rating"], 4.2) * 18
            + max(0, 20 - dist)
            + destination_priority_score(policy, poi),
            2,
        )
        dedupe_key = dedupe_name_key(name)
        existing = pois_by_key.get(dedupe_key)
        if existing is None:
            pois_by_key[dedupe_key] = poi
            continue
        existing_is_sub = is_complex_sub_poi(str(existing.get("name", "")), str(existing.get("type", "")))
        current_is_sub = is_complex_sub_poi(name, type_text)
        if existing_is_sub and not current_is_sub:
            pois_by_key[dedupe_key] = poi
            continue
        if current_is_sub and not existing_is_sub:
            continue
        existing_score = (
            float(existing.get("popularity_score", 0.0) or 0.0),
            -len(str(existing.get("name", ""))),
            _safe_float(existing.get("rating"), 0.0),
        )
        current_score = (
            float(poi.get("popularity_score", 0.0) or 0.0),
            -len(name),
            _safe_float(poi.get("rating"), 0.0),
        )
        if current_score > existing_score:
            pois_by_key[dedupe_key] = poi

    pois = list(pois_by_key.values())
    if policy.restrict_to_single_city:
        clustered = restrict_to_primary_city_cluster(pois)
        min_keep = 4 if policy.style_key == "adventure" else max(6, min(10, len(pois) // 2))
        if len(clustered) >= min_keep:
            pois = clustered
    # 单城收敛后同样要做景区簇去重，否则「伊犁」类目的地会在列表里堆满同一品牌的子地点。
    pois = dedupe_by_scenic_cluster(pois, seed_names=policy.seed_name_set(), max_per_cluster=1)
    pois = sorted(pois, key=lambda item: (item["popularity_score"], _safe_float(item.get("rating"), 0.0)), reverse=True)[:22]
    visit_profiles = merged_visit_profiles_for_destination(destination)
    return [
        enrich_poi_with_activity_load(poi, destination=destination, visit_profiles=visit_profiles)
        for poi in pois
    ]
