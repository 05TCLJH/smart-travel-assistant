"""景点游览指标统一解析入口。

架构分层：
1. 场馆形态模块负责景点形态分类，以及各形态的默认时长、负荷和排期模式
2. 游览时长模块负责档位区间、边界收敛与指标组合，保持纯计算逻辑
3. 本模块负责合并知识库画像、导游种子与规则兜底，对外只暴露统一解析入口

下游负荷评估、画像匹配、排期策略与导游估算模块
均应调用本模块，禁止再散落「主题乐园六小时」这类分支。
"""

from __future__ import annotations

from typing import Any

from backend.planning.venue_archetype import (
    VenueArchetype,
    metrics_from_poi_archetype,
    resolve_venue_archetype_from_poi,
)
from backend.planning.visit_duration import TIER_HOURS_RANGE, TIER_LOAD, compose_visit_metrics, infer_schedule_mode

# 场馆形态默认时长为锚点；知识库偏离超过该阈值时回退到形态默认值，避免陈旧画像失真
_PROFILE_ANCHOR_DRIFT_HOURS = 1.0

# 强锚形态：知识库不得压低/抬高到另一档位
# 强锚规则：旧画像不得把场馆形态拉偏，例如把主题乐园写成两小时或把大山景区缩成半日
_STRONGLY_ANCHORED_ARCHETYPES = frozenset(
    {
        "theme_park",
        "museum_major",
        "palace_museum",
        "scenic_half_day",
        "scenic_full_day",
        "scenic_city_hill",
    }
)


def _hours_band(spec: VenueArchetype) -> tuple[float, float]:
    mode = spec.schedule_mode  # type: ignore[arg-type]
    tier = spec.tier
    return TIER_HOURS_RANGE.get(mode, TIER_HOURS_RANGE["flexible"]).get(tier, (1.5, 3.0))


def apply_archetype_to_profile(
    profile: dict[str, Any],
    spec: VenueArchetype,
    *,
    poi: dict[str, Any],
) -> dict[str, Any]:
    """知识库画像在 archetype 约束下校准；强锚形态以注册表为准，泛型 POI 以画像档位为准。"""
    profile_tier = str(profile.get("activity_tier", "") or "").strip().lower()
    tier = profile_tier if profile_tier in TIER_LOAD else spec.tier
    mode = spec.schedule_mode
    if spec.archetype != "generic_standard":
        tier = spec.tier
        mode = spec.schedule_mode
    else:
        mode = infer_schedule_mode(poi)  # type: ignore[assignment]
    lo, hi = TIER_HOURS_RANGE.get(mode, TIER_HOURS_RANGE["flexible"]).get(tier, (1.5, 3.0))

    hours_hint: float | None = None
    for key in ("typical_visit_hours", "visit_hours"):
        raw = profile.get(key)
        if raw is not None:
            try:
                hours_hint = float(raw)
            except (TypeError, ValueError):
                hours_hint = None
            break

    if spec.archetype in _STRONGLY_ANCHORED_ARCHETYPES:
        if hours_hint is None or abs(hours_hint - spec.visit_hours) >= _PROFILE_ANCHOR_DRIFT_HOURS:
            hours = spec.visit_hours
        else:
            hours = max(lo, min(hours_hint, hi))
    elif hours_hint is None:
        hours = spec.visit_hours
    else:
        hours = max(lo, min(hours_hint, hi))

    load = TIER_LOAD.get(tier, spec.activity_load)
    if spec.archetype in _STRONGLY_ANCHORED_ARCHETYPES:
        load = spec.activity_load

    composed = compose_visit_metrics(
        activity_load=load,
        activity_tier=tier,
        poi=poi,
        typical_visit_hours=hours,
        schedule_mode=mode,  # type: ignore[arg-type]
    )
    return {
        **composed,
        "venue_archetype": spec.archetype,
        "pairing_role": spec.pairing_role,
        "activity_load_source": "knowledge",
        "knowledge_visit_profile": hours_hint if hours_hint is not None else spec.visit_hours,
    }


def resolve_poi_visit_metrics(
    poi: dict[str, Any],
    *,
    visit_profiles: dict[str, dict[str, Any]] | None = None,
    destination: str | None = None,
    region_type: str | None = None,
) -> dict[str, Any]:
    """为单个 POI 生成一致的 activity_load / visit_hours / schedule_mode。"""
    from backend.knowledge.destination_catalog import get_curated_profile
    from backend.knowledge.visit_profiles import match_visit_profile

    item = dict(poi)
    name = str(item.get("name", "")).strip()

    region = str(region_type or "city").strip().lower()
    if not region_type and destination:
        dest_profile = get_curated_profile(destination)
        if dest_profile:
            region = str(dest_profile.get("region_type", "city") or "city").strip().lower()

    spec = resolve_venue_archetype_from_poi(item, region_type=region)

    if visit_profiles:
        matched = match_visit_profile(name, visit_profiles)
        if matched:
            return apply_archetype_to_profile(matched, spec, poi=item)

    archetype_metrics = metrics_from_poi_archetype(item, region_type=region)
    if archetype_metrics.get("venue_archetype") != "generic_standard":
        payload = dict(archetype_metrics)
        payload["activity_load_source"] = "guide"
        return payload

    from backend.planning.activity_load import _estimate_activity_load_rules

    rules = _estimate_activity_load_rules(item)
    payload = dict(rules)
    payload["venue_archetype"] = spec.archetype
    payload["pairing_role"] = spec.pairing_role
    return payload


def enrich_visit_fields(poi: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    """写入排期字段（prepare_day_pois / enrich 共用）。"""
    out = dict(poi)
    for key in (
        "visit_hours",
        "visit_hours_display",
        "activity_tier",
        "activity_tier_label",
        "activity_load",
        "schedule_mode",
        "venue_archetype",
        "pairing_role",
        "activity_load_source",
    ):
        if key in metrics:
            out[key] = metrics[key]
    out["visit_hours_display"] = out.get("visit_hours_display", out.get("visit_hours"))
    return out
