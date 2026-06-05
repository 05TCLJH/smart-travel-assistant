"""旅行风格亲和度：统一评分、软排序与极少数硬否决。

用于替代过于僵硬的二元筛选，避免小众探索场景下候选池过早枯竭。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.planning.planning_profile import resolve_planning_profile
from backend.planning.search_strategy import normalize_style_key
from backend.tools.grounding_tools import normalize_poi_tags, preferred_tags

# 与候选评分模块中的关键词保持一致，集中供全链路引用
OFFBEAT_POSITIVE = (
    "老街",
    "街区",
    "步道",
    "创意园",
    "创意",
    "艺术",
    "文创",
    "市集",
    "码头",
    "巷",
    "里弄",
    "旧居",
    "书店",
    "湿地",
    "江边",
    "湖畔",
    "艺术区",
    "工业",
)
OFFBEAT_NEGATIVE = (
    "游客中心",
    "服务中心",
    "必去",
    "地标",
    "经典",
    "网红打卡",
    "国旗",
)
NICHE_LOW_VALUE_MUSEUM = (
    "警察",
    "消防",
    "税务",
    "禁毒",
    "钱币",
    "地质",
    "老酒",
    "巧克力",
    "航天",
    "昆虫",
    "附属医院",
)


@dataclass(frozen=True)
class StyleAffinity:
    score: float
    tier: str  # 亲和度分层：高 / 中 / 低
    veto: str | None = None


def _style_key(persona: dict[str, Any]) -> str:
    key = str(persona.get("style_key", "")).strip()
    if key in {"classic", "offbeat", "leisure", "adventure", "cultural"}:
        return key
    return normalize_style_key(str(persona.get("travel_style", "")))


def hard_style_veto(poi: dict[str, Any], persona: dict[str, Any]) -> str | None:
    """仅否决与风格明显冲突的类型（不做「小众=不要博物馆」一刀切）。"""
    style = _style_key(persona)
    name = str(poi.get("name", "")).strip()
    tags = set(poi.get("canonical_tags", []) or normalize_poi_tags(poi))

    if style == "offbeat":
        if any(token in name for token in OFFBEAT_NEGATIVE):
            return "offbeat_avoid_keyword"
        if "city_landmark" in tags and not (tags & {"street", "niche"}):
            if any(token in name for token in ("广场", "塔", "大桥", "摩天轮", "观景")):
                return "offbeat_landmark"
        if "museum" in tags and not (tags & {"street", "niche"}):
            if any(token in name for token in NICHE_LOW_VALUE_MUSEUM):
                return "offbeat_low_value_museum"
            if not any(token in name for token in OFFBEAT_POSITIVE):
                return "offbeat_generic_museum"
    elif style == "adventure":
        if not (tags & {"nature", "niche"}) and not any(
            token in name for token in ("徒步", "森林", "山", "峡谷", "草原", "湿地", "步道")
        ):
            if tags & {"museum", "indoor"} and "street" not in tags:
                return "adventure_indoor_only"
    elif style == "cultural":
        if tags & {"city_landmark"} and not (tags & {"museum", "history_culture", "street"}):
            return "cultural_shallow_landmark"
    elif style == "leisure":
        if any(token in name for token in ("徒步", "登山", "越野", "攀岩")):
            return "leisure_too_intense"
    return None


def compute_style_affinity(poi: dict[str, Any], persona: dict[str, Any]) -> StyleAffinity:
    veto = hard_style_veto(poi, persona)
    if veto:
        return StyleAffinity(score=0.0, tier="C", veto=veto)

    style = _style_key(persona)
    name = str(poi.get("name", "")).strip()
    tags = set(poi.get("canonical_tags", []) or normalize_poi_tags(poi))
    preferred = preferred_tags(persona)
    overlap = tags & preferred

    score = 42.0
    score += len(overlap) * 9.0
    if poi.get("preference_hit"):
        score += 10.0

    mainstream = float(persona.get("mainstream_preference", 0.5) or 0.5)
    popularity = float(poi.get("popularity_score", 60.0) or 60.0)
    score += (popularity - 55.0) * (mainstream - 0.5) * 0.35

    if style == "offbeat":
        if any(token in name for token in OFFBEAT_POSITIVE):
            score += 22.0
        if "street" in tags:
            score += 24.0
        if "niche" in tags:
            score += 18.0
        if "nature" in tags:
            score += 12.0
        if "history_culture" in tags and "street" in tags:
            score += 14.0
        if "city_landmark" in tags:
            score -= 22.0
        if "museum" in tags and "street" not in tags:
            score -= 8.0
    elif style == "cultural":
        if "museum" in tags:
            score += 20.0
        if "history_culture" in tags:
            score += 16.0
        if "street" in tags:
            score += 12.0
        if "city_landmark" in tags and not (tags & {"museum", "history_culture"}):
            score -= 10.0
    elif style == "leisure":
        if tags & {"nature", "street", "night_view"}:
            score += 14.0
        if any(token in name for token in ("公园", "江滩", "湖滨", "步道", "夜市", "温泉", "慢游")):
            score += 12.0
        if "city_landmark" in tags and not any(token in name for token in ("徒步", "登山", "越野")):
            score += 6.0
    elif style == "adventure":
        if "nature" in tags:
            score += 22.0
        if any(token in name for token in ("徒步", "森林", "山", "草原", "峡谷", "湿地")):
            score += 16.0
    elif style == "classic":
        if "city_landmark" in tags:
            score += 18.0
        for hotspot in persona.get("destination_hotspots", []) or []:
            if str(hotspot).strip() and str(hotspot).strip() in name:
                score += 20.0

    score = max(0.0, min(100.0, round(score, 2)))
    if score >= 68.0:
        tier = "A"
    elif score >= 48.0:
        tier = "B"
    else:
        tier = "C"
    return StyleAffinity(score=score, tier=tier)


def enrich_with_style_affinity(poi: dict[str, Any], persona: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(poi)
    aff = compute_style_affinity(enriched, persona)
    enriched["style_affinity"] = aff.score
    enriched["style_tier"] = aff.tier
    enriched["style_veto"] = aff.veto
    return enriched


def rank_by_style_affinity(
    pois: list[dict[str, Any]],
    persona: dict[str, Any],
    *,
    min_affinity: float = 0.0,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for poi in pois:
        item = enrich_with_style_affinity(poi, persona)
        if item.get("style_veto"):
            continue
        if float(item.get("style_affinity", 0) or 0) < min_affinity:
            continue
        kept.append(item)
    return sorted(
        kept,
        key=lambda row: (
            float(row.get("style_affinity", 0) or 0),
            float(row.get("suitability_score", 0) or 0),
            float(row.get("constraint_score", 0) or 0),
            bool(row.get("preference_hit")),
        ),
        reverse=True,
    )


def select_planning_pool(
    ranked: list[dict[str, Any]],
    persona: dict[str, Any],
    *,
    required_total: int,
    days: int,
    strict_style: bool,
) -> list[dict[str, Any]]:
    """规划用候选：风格亲和度排序 + 多样性装箱，保证池子够大。"""
    from backend.planning.candidate_selection import select_diverse_candidates

    planning_profile = resolve_planning_profile(persona, days=days)
    min_affinity = 40.0 if strict_style else 32.0
    style_ranked = rank_by_style_affinity(ranked, persona, min_affinity=min_affinity)
    if len(style_ranked) < max(required_total, planning_profile.candidate_expansion_threshold):
        style_ranked = rank_by_style_affinity(ranked, persona, min_affinity=28.0)
    if len(style_ranked) < max(required_total, planning_profile.candidate_floor):
        style_ranked = rank_by_style_affinity(ranked, persona, min_affinity=0.0)

    target = max(required_total, planning_profile.planning_pool_target, 8)
    return select_diverse_candidates(style_ranked, persona, target, days)
