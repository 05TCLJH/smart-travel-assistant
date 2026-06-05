"""候选景点评分模块。

负责根据用户画像、天气、偏好标签与景点属性计算候选分，并输出稳定排序结果。
"""

from __future__ import annotations

from typing import Any

from backend.planning import style_profile
from backend.planning.activity_load import enrich_poi_with_activity_load
from backend.tools.grounding_tools import (
    is_auxiliary_poi,
    is_generic_urban_poi,
    normalize_poi_tags,
    preferred_tags,
)


MAINSTREAM_POSITIVE_KEYWORDS = (
    "博物院",
    "博物馆",
    "总统府",
    "夫子庙",
    "老门东",
    "城墙",
    "古城",
    "钟楼",
    "鼓楼",
    "寺",
    "宫",
    "庙",
    "塔",
    "湖",
    "园",
    "陵",
    "广场",
    "长城",
    "历史文化街区",
    "景区",
    "草原",
    "古道",
    "峡谷",
    "薰衣草",
    "大桥",
    "杏花",
)
MAINSTREAM_NEGATIVE_KEYWORDS = (
    "故居",
    "旧居",
    "片区",
    "办公楼",
    "服务中心",
    "文创",
    "检票处",
    "售票处",
    "书屋",
    "建设中",
    "不对外开放",
)
OFFBEAT_POSITIVE_KEYWORDS = (
    "老街",
    "街区",
    "步道",
    "创意园",
    "市集",
    "码头",
    "巷",
    "村",
    "书店",
    "湿地",
    "江边",
    "湖畔",
    "公园",
)
OFFBEAT_NEGATIVE_KEYWORDS = (
    "广场",
    "游客中心",
    "服务中心",
    "必去",
    "地标",
    "经典",
    "网红",
    "国旗",
)


def passes_style_guard(poi: dict[str, Any], persona: dict[str, Any]) -> bool:
    """判断景点是否触发风格硬否决。"""
    from backend.planning.style_affinity import hard_style_veto

    return hard_style_veto(poi, persona) is None


def mainstream_score(poi: dict[str, Any], persona: dict[str, Any]) -> float:
    """计算经典风格用户对主流景点的附加偏好分。"""
    if not style_profile.is_classic_style(persona):
        return 0.0
    name = str(poi.get("name", "")).strip()
    tags = set(poi.get("canonical_tags", []) or normalize_poi_tags(poi))
    score = 0.0
    if "city_landmark" in tags:
        score += 18.0
    if "history_culture" in tags:
        score += 8.0
    if "museum" in tags:
        score += 4.0
    if any(token in name for token in MAINSTREAM_POSITIVE_KEYWORDS):
        score += 10.0
    for hotspot in persona.get("destination_hotspots", []) or []:
        text = str(hotspot).strip()
        if text and text in name:
            score += 24.0
    if any(token in name for token in MAINSTREAM_NEGATIVE_KEYWORDS):
        score -= 18.0
    if "故居" in name or "旧居" in name:
        score -= 12.0
    return score


def score_candidate(
    poi: dict[str, Any],
    persona: dict[str, Any],
    weather: dict[str, Any],
    routing_policy: dict[str, Any] | None = None,
) -> float:
    """综合人群偏好、天气、距离与票价信息给单个候选打分。"""
    popularity = float(poi.get("popularity_score", 60.0) or 60.0)
    mainstream_preference = float(
        poi.get("mainstream_preference", persona.get("mainstream_preference", 0.5)) or 0.5
    )
    score = popularity * (0.35 + mainstream_preference * 0.65)
    tags = normalize_poi_tags(poi)
    preferred = preferred_tags(persona)
    matched_tags = tags & preferred
    score += len(matched_tags) * 10
    score += float(poi.get("constraint_score", 0.0) or 0.0) * 0.3
    if poi.get("preference_hit"):
        score += 18
    elif preferred:
        score -= 16
    score += mainstream_score(poi, persona)
    name = str(poi.get("name", "")).strip()

    if style_profile.is_offbeat_style(persona):
        if any(token in name for token in OFFBEAT_POSITIVE_KEYWORDS):
            score += 16
        if any(token in name for token in OFFBEAT_NEGATIVE_KEYWORDS):
            score -= 18
        if "street" in tags:
            score += 20
        if "nature" in tags:
            score += 10
        if "city_landmark" in tags:
            score -= 20
        if "museum" in tags and "history_culture" in tags:
            score -= 6
    elif style_profile.is_cultural_style(persona):
        if "museum" in tags:
            score += 18
        if "history_culture" in tags:
            score += 14
        if "city_landmark" in tags and not (tags & {"museum", "history_culture"}):
            score -= 8
    elif style_profile.is_leisure_style(persona):
        if "nature" in tags or "street" in tags:
            score += 12

    distance = float(poi.get("distance_to_destination_km", 0.0) or 0.0)
    score -= distance * 0.7
    if distance > 20:
        score -= (distance - 20) * 1.2
    if distance > 35:
        score -= (distance - 35) * 1.6
    transport_preference = str(persona.get("transport_preference", "")).strip()
    if distance > 25 and any(token in transport_preference for token in ("步行", "公交", "地铁")):
        score -= 10

    if weather.get("rating") == "较差" and "nature" in tags:
        score -= 10
    if preferred & {"history_culture", "museum"}:
        if "history_culture" in tags:
            score += 16
        if "museum" in tags:
            score += 14
        if "nature" in tags and not (tags & {"history_culture", "museum"}):
            score -= 12
        if "city_landmark" in tags and not (tags & {"history_culture", "museum"}):
            score -= 4
    if preferred & {"city_landmark"} and "city_landmark" in tags:
        score += 8
    if is_auxiliary_poi(poi):
        score -= 22
    if preferred & {"history_culture", "museum"} and "city_landmark" not in preferred and is_generic_urban_poi(poi) and not (tags & {"history_culture", "museum"}):
        score -= 24

    cost = str(poi.get("ticket", poi.get("cost", ""))).strip()
    if cost and cost not in {"未知", "免费"}:
        try:
            score -= float(cost) * 0.05
        except ValueError:
            pass

    rp = routing_policy or {}
    if rp.get("prefer_indoor_on_bad_weather"):
        rating = str(weather.get("rating", "") or "").strip()
        if rating in ("较差", "一般"):
            if tags & {"museum", "history_culture"} or any(
                key in name for key in ("博物馆", "纪念馆", "美术馆", "展览")
            ):
                score += 14
            if "nature" in tags:
                score -= 9

    return round(score, 2)


def rank_candidates(
    candidate_pois: list[dict[str, Any]],
    persona: dict[str, Any],
    weather: dict[str, Any],
    routing_policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """补齐标签和活动负荷信息后，按综合分稳定排序。"""
    ranked = []
    preferred = preferred_tags(persona)
    destination = str(persona.get("current_destination") or persona.get("destination") or "").strip()
    for poi in candidate_pois:
        enriched = dict(poi)
        tags = normalize_poi_tags(enriched)
        matched_tags = sorted(tags & preferred)
        enriched["canonical_tags"] = sorted(tags)
        enriched["matched_preference_tags"] = matched_tags
        enriched["preference_hit"] = bool(matched_tags)
        enriched = enrich_poi_with_activity_load(enriched, destination=destination or None)
        enriched["suitability_score"] = score_candidate(
            enriched,
            persona,
            weather,
            routing_policy=routing_policy,
        )
        ranked.append(enriched)
    return sorted(
        ranked,
        key=lambda item: (
            bool(item.get("preference_hit")),
            item.get("suitability_score", 0.0),
            item.get("constraint_score", 0.0),
        ),
        reverse=True,
    )
