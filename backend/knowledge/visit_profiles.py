"""目的地游览画像：匹配 + 规范化。"""

from __future__ import annotations

import re
from typing import Any

from backend.planning.venue_archetype import resolve_venue_archetype_from_poi
from backend.planning.venue_visit_resolver import apply_archetype_to_profile
from backend.planning.visit_duration import (
    TIER_LABELS,
    compose_visit_metrics,
    hours_to_load,
    infer_schedule_mode,
)

# 高德地点名称噪声（去掉后更易命中热点种子）
_POI_NOISE_SUFFIXES = (
    "有限责任公司",
    "股份有限公司",
    "旗舰店",
    "专卖店",
    "连锁店",
    "分公司",
    "营业部",
    "游客中心",
    "服务中心",
    "售票处",
    "检票口",
    "出入口",
    "停车场",
    "南门",
    "北门",
    "东门",
    "西门",
    "正门",
    "大门",
    "度假酒店",
    "酒店",
    "餐厅",
    "咖啡",
    "便利店",
    "店)",
    "店",
)

_NOISE_RE = re.compile(
    r"[（(][^)）]*(店|出口|入口|门|停车场|售票)[)）]?|"
    r"(?:旗舰店|专卖店|游客中心|售票处|检票口|停车场)$"
)


def hotspot_entry_name(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("name", "")).strip()
    return str(entry).strip()


def normalize_poi_name_for_match(name: str) -> str:
    """便于与知识库种子做子串匹配的名称清洗。"""
    text = str(name or "").strip()
    if not text:
        return ""
    text = _NOISE_RE.sub("", text)
    for noise in _POI_NOISE_SUFFIXES:
        if text.endswith(noise) and len(text) > len(noise) + 2:
            text = text[: -len(noise)].strip("·-—－()（） ")
    return text.strip()


def _match_score(poi_name: str, seed: str) -> int:
    if not poi_name or not seed:
        return 0
    norm_poi = normalize_poi_name_for_match(poi_name)
    norm_seed = normalize_poi_name_for_match(seed)
    if not norm_poi or not norm_seed:
        return 0
    if norm_seed in norm_poi:
        return len(norm_seed) + 20
    if len(norm_poi) >= 4 and norm_poi in norm_seed:
        return len(norm_poi) + 10
    prefix = norm_seed[: min(4, len(norm_seed))]
    if len(prefix) >= 2 and norm_poi.startswith(prefix):
        return len(prefix) + 5
    return 0


def match_visit_profile(poi_name: str, profiles: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """按匹配得分选最优种子画像（越长、越贴合越好）。"""
    name = str(poi_name or "").strip()
    if not name or not profiles:
        return None
    best_key = ""
    best_score = 0
    best_profile: dict[str, Any] | None = None
    for key, raw in profiles.items():
        seed = str(key).strip()
        if not seed or not isinstance(raw, dict):
            continue
        score = _match_score(name, seed)
        if score > best_score:
            best_score = score
            best_key = seed
            best_profile = raw
    if not best_profile or best_score < 3:
        return None
    return normalize_visit_profile(best_profile, poi_name=name)


def normalize_visit_profile(raw: dict[str, Any], *, poi_name: str = "") -> dict[str, Any]:
    poi_stub = {"name": poi_name or str(raw.get("name", ""))}
    spec = resolve_venue_archetype_from_poi(poi_stub)
    if spec.archetype != "generic_standard":
        merged = apply_archetype_to_profile(raw, spec, poi=poi_stub)
        return {
            "typical_visit_hours": merged["visit_hours"],
            "activity_tier": merged["activity_tier"],
            "activity_load": merged["activity_load"],
            "visit_hours": merged["visit_hours"],
            "activity_tier_label": merged["activity_tier_label"],
            "schedule_mode": merged["schedule_mode"],
        }

    tier = str(raw.get("activity_tier", "")).strip().lower() or None
    hours_raw = raw.get("typical_visit_hours", raw.get("visit_hours"))
    try:
        hours_f = float(hours_raw) if hours_raw is not None else None
    except (TypeError, ValueError):
        hours_f = None

    poi_stub = {"name": poi_name or str(raw.get("name", ""))}
    mode = infer_schedule_mode(poi_stub)
    if not tier:
        tier = "standard"
    metrics = compose_visit_metrics(
        activity_load=hours_to_load(hours_f or 2.0, tier),
        activity_tier=tier,
        poi=poi_stub,
        typical_visit_hours=hours_f,
        schedule_mode=mode,
    )
    return {
        "typical_visit_hours": metrics["visit_hours"],
        "activity_tier": metrics["activity_tier"],
        "activity_load": metrics["activity_load"],
        "visit_hours": metrics["visit_hours"],
        "activity_tier_label": metrics["activity_tier_label"],
        "schedule_mode": metrics["schedule_mode"],
    }


def metrics_from_visit_profile(profile: dict[str, Any], *, poi_name: str = "") -> dict[str, Any]:
    normalized = normalize_visit_profile(profile, poi_name=poi_name)
    return {
        "activity_load": normalized["activity_load"],
        "visit_hours": normalized["visit_hours"],
        "activity_tier": normalized["activity_tier"],
        "activity_tier_label": normalized["activity_tier_label"],
        "schedule_mode": normalized["schedule_mode"],
        "activity_load_source": "knowledge",
        "knowledge_visit_profile": normalized.get("typical_visit_hours"),
    }
