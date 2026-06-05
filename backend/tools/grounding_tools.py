"""落地校验与约束检查工具，降低幻觉与错配。"""

from __future__ import annotations

from typing import Any

TAG_LABELS = {
    "history_culture": "历史文化",
    "museum": "博物馆",
    "nature": "自然风景",
    "city_landmark": "城市地标",
    "night_view": "夜景",
    "niche": "小众",
    "food": "美食",
    "street": "街区",
    "indoor": "室内",
}


PROVINCE_LEVEL_NAMES = {
    "北京",
    "天津",
    "上海",
    "重庆",
    "河北",
    "山西",
    "辽宁",
    "吉林",
    "黑龙江",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "海南",
    "四川",
    "贵州",
    "云南",
    "陕西",
    "甘肃",
    "青海",
    "台湾",
    "内蒙古",
    "广西",
    "西藏",
    "宁夏",
    "新疆",
    "香港",
    "澳门",
}

ADMIN_SUFFIXES = (
    "维吾尔自治区",
    "壮族自治区",
    "回族自治区",
    "特别行政区",
    "自治区",
    "自治州",
    "省",
    "市",
    "地区",
    "盟",
    "州",
    "县",
    "区",
)


TAG_RULES = {
    "history_culture": ("历史", "文化", "古迹", "遗址", "古城", "古镇", "纪念", "祠", "阁", "楼", "寺", "院"),
    "museum": ("博物馆", "纪念馆", "展览馆", "美术馆", "科技馆"),
    "nature": ("自然", "公园", "山", "湖", "湿地", "森林", "风景", "景区", "海", "岛"),
    "city_landmark": ("地标", "广场", "塔", "标志", "城市代表", "观景台", "长城"),
    "night_view": ("夜景", "夜游", "灯光", "喷泉"),
    "niche": ("小众", "秘境", "冷门", "本地体验", "本地人", "小众景点"),
    "food": ("美食", "小吃", "餐厅", "夜市"),
    "street": ("街区", "老街", "步行街", "里弄", "巷", "创意园", "艺术区", "文创", "艺术", "街头"),
    "indoor": ("博物馆", "纪念馆", "展览", "美术馆", "科技馆", "书店", "室内", "街区"),
}


AUXILIARY_KEYWORDS = (
    "停车场",
    "售票处",
    "售票点",
    "验票点",
    "验票",
    "游客中心",
    "服务中心",
    "公交站",
    "地铁站",
    "派出所",
    "检票口",
    "观光厅",
    "纪念品",
    "礼品店",
    "精品客栈",
    "客栈",
    "北园",
    "南门",
    "东门",
    "西门",
    "游轮",
)


GENERIC_URBAN_KEYWORDS = ("广场", "市民公园", "观光厅", "摩天轮", "音乐喷泉", "双子塔")
SECONDARY_POI_SUFFIXES = ("片区", "检票处", "售票处", "验票点", "服务中心", "游客中心", "办公楼", "观景台")
SECONDARY_POI_SEPARATORS = ("-", "－", "—", "(", "（")
SECONDARY_POI_KEYWORDS = ("门", "桥", "角楼", "城楼", "国旗", "展厅", "片区", "停车场", "球场", "观景台")


def _collect_tokens(*parts: Any) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, (list, tuple, set)):
            chunks.extend(str(item).strip() for item in part if str(item).strip())
        else:
            text = str(part or "").strip()
            if text:
                chunks.append(text)
    return " ".join(chunks)


def normalize_admin_name(text: Any) -> str:
    normalized = str(text or "").strip().replace(" ", "")
    if not normalized:
        return ""
    for suffix in ADMIN_SUFFIXES:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    for token in ("维吾尔", "壮族", "回族"):
        normalized = normalized.replace(token, "")
    return normalized.strip()


def admin_aliases(text: Any) -> set[str]:
    raw = str(text or "").strip()
    normalized = normalize_admin_name(raw)
    aliases = {item for item in {raw, normalized} if item}
    if normalized:
        aliases.add(normalized.replace("省", "").replace("市", ""))
    return aliases


def is_province_level_destination_name(text: Any) -> bool:
    raw = str(text or "").strip()
    normalized = normalize_admin_name(raw)
    if not normalized:
        return False
    if any(raw.endswith(suffix) for suffix in ("省", "自治区", "特别行政区")):
        return True
    return normalized in PROVINCE_LEVEL_NAMES


def canonical_tags_from_text(*parts: Any) -> set[str]:
    haystack = _collect_tokens(*parts)
    tags: set[str] = set()
    for key, rules in TAG_RULES.items():
        if any(token in haystack for token in rules):
            tags.add(key)
    if "nature" in tags and "广场" in haystack and not any(token in haystack for token in ("森林", "湿地", "山", "湖", "海", "郊野")):
        tags.discard("nature")
    if "nature" in tags and "history_culture" in tags and not any(token in haystack for token in ("自然", "公园", "森林", "湿地", "山", "湖", "海", "岛", "郊野")):
        tags.discard("nature")
    if "museum" in tags:
        tags.add("history_culture")
        tags.add("indoor")
    if "street" in tags:
        tags.add("history_culture")
    return tags


def display_tags(tags: set[str]) -> list[str]:
    return [TAG_LABELS[tag] for tag in sorted(tags) if tag in TAG_LABELS]


_CANONICAL_INTEREST_KEYS = frozenset(TAG_LABELS)


def preferred_tags(persona: dict[str, Any]) -> set[str]:
    likes = persona.get("likes", []) or []
    interests = persona.get("interests", []) or []
    preferred_types = persona.get("preferred_poi_types", []) or []
    preferred_keywords = persona.get("preferred_keywords", []) or []
    style = str(persona.get("travel_style", "")).strip()
    tags = canonical_tags_from_text(likes, preferred_types, preferred_keywords, style)
    for key in interests:
        token = str(key).strip()
        if token in _CANONICAL_INTEREST_KEYS:
            tags.add(token)
    return tags


def strict_style_mode(persona: dict[str, Any]) -> bool:
    """强风格画像：启用亲和度排序与硬否决，但不再「只保留 preference_hit」。"""
    route_style = str(persona.get("route_style", "")).strip().lower()
    mainstream_preference = float(persona.get("mainstream_preference", 0.5) or 0.5)
    return route_style in {"discovery", "active", "deep"} or mainstream_preference <= 0.35


def normalize_poi_tags(poi: dict[str, Any]) -> set[str]:
    return canonical_tags_from_text(
        poi.get("name", ""),
        poi.get("type", ""),
        poi.get("knowledge_tags", []),
    )


def indoors_friendly(poi: dict[str, Any]) -> bool:
    tags = normalize_poi_tags(poi)
    return bool({"museum", "indoor", "street", "history_culture"} & tags)


def is_auxiliary_poi(poi: dict[str, Any]) -> bool:
    haystack = _collect_tokens(poi.get("name", ""), poi.get("type", ""))
    return any(token in haystack for token in AUXILIARY_KEYWORDS)


def is_generic_urban_poi(poi: dict[str, Any]) -> bool:
    haystack = _collect_tokens(poi.get("name", ""), poi.get("type", ""))
    return any(token in haystack for token in GENERIC_URBAN_KEYWORDS)


def is_secondary_poi(poi: dict[str, Any]) -> bool:
    name = str(poi.get("name", "")).strip()
    type_text = str(poi.get("type", "")).strip()
    if not name:
        return False
    if any(name.endswith(suffix) for suffix in SECONDARY_POI_SUFFIXES):
        return True
    if any(separator in name for separator in SECONDARY_POI_SEPARATORS) and any(token in name for token in SECONDARY_POI_KEYWORDS):
        return True
    if "风景名胜相关" in type_text and any(token in name for token in SECONDARY_POI_KEYWORDS):
        return True
    return False


def destination_conflict(poi: dict[str, Any], destination: str, persona: dict[str, Any] | None = None) -> bool:
    from backend.planning.destination_constraints import resolve_constraint_profile

    destination_text = str(destination or "").strip()
    if not destination_text:
        return False
    return resolve_constraint_profile(destination_text, persona).admin_conflict(poi)


def evaluate_candidate_match(
    poi: dict[str, Any],
    request_payload: dict[str, Any],
    persona: dict[str, Any],
    weather: dict[str, Any],
) -> dict[str, Any]:
    from backend.planning.destination_constraints import resolve_constraint_profile

    reasons: list[str] = []
    warnings: list[str] = []
    hard_block = False
    score = 60.0
    destination = str(request_payload.get("destination", "")).strip()
    constraint = resolve_constraint_profile(destination, persona)

    tags = normalize_poi_tags(poi)
    preferred = preferred_tags(persona)
    overlap = tags & preferred
    if overlap:
        score += len(overlap) * 12
        reasons.append(f"命中偏好标签：{'/'.join(display_tags(overlap))}")
    elif preferred:
        warnings.append("与当前核心偏好标签重合较少")
        score -= 12

    if is_auxiliary_poi(poi):
        warnings.append("更像附属设施或次级点位，不适合作为核心行程点")
        score -= 18
    if is_secondary_poi(poi):
        warnings.append("更像景区内部次级点位，不适合作为主行程目的地")
        score -= 24

    if preferred & {"history_culture", "museum"} and is_generic_urban_poi(poi) and not (tags & {"history_culture", "museum"}):
        warnings.append("偏通用城市打卡点，与文化深度游贴合度一般")
        score -= 10

    distance = float(poi.get("distance_to_destination_km", 0.0) or 0.0)
    remote_km = constraint.remote_distance_threshold_km
    if distance <= 5:
        score += 8
        reasons.append("距离目的地较近")
    elif distance > remote_km:
        warnings.append("距离目的地偏远")
        score -= 16 if constraint.is_wide_area else 10

    from backend.planning.budget_style import normalize_budget_style, ticket_warning_threshold

    budget_style = normalize_budget_style(persona.get("budget_style"))
    ticket = str(poi.get("ticket", poi.get("cost", ""))).strip()
    if ticket not in {"", "未知", "免费"}:
        try:
            ticket_value = float(ticket)
        except ValueError:
            ticket_value = 0.0
        threshold = ticket_warning_threshold(budget_style)
        if budget_style == "经济" and ticket_value >= threshold:
            warnings.append("门票对经济型预算不友好")
            score -= 14
        elif ticket_value >= threshold:
            warnings.append("门票价格偏高")
            score -= 8 if budget_style == "舒适" else 4

    from backend.planning.stamina_profile import normalize_stamina

    stamina = normalize_stamina(persona.get("stamina", "适中"))
    if stamina == "轻松" and distance > 12:
        warnings.append("当前体力画像下交通负担偏大")
        score -= 10

    if weather.get("rating") == "较差" and not indoors_friendly(poi):
        warnings.append("天气较差时该景点的室外属性较强")
        score -= 12
    elif weather.get("rating") == "较差" and indoors_friendly(poi):
        reasons.append("恶劣天气下仍可作为室内备选")
        score += 6

    from backend.planning.poi_roles import PoiRole, resolve_poi_role

    if resolve_poi_role(poi) not in {
        PoiRole.SCENIC,
        PoiRole.CULTURAL,
        PoiRole.STREET_LANDMARK,
        PoiRole.CITY_LANDMARK,
        PoiRole.UNKNOWN,
    }:
        hard_block = True
        warnings.append("非行程主线类型（如零售/餐饮/交通附属），已排除")
    if constraint.admin_conflict(poi):
        warnings.append("POI 行政区信息与目的地范围不一致")
        if constraint.is_wide_area:
            score -= 28
            if distance > constraint.search_radius_km:
                hard_block = True
        else:
            score -= 45
            hard_block = True
    if is_secondary_poi(poi) and score < 70:
        hard_block = True

    return {
        "score": round(score, 2),
        "reasons": reasons,
        "warnings": warnings,
        "is_match": (score >= 55) and not hard_block,
        "preference_hit": bool(overlap),
        "matched_preference_tags": display_tags(overlap),
        "canonical_tags": sorted(tags),
        "hard_block": hard_block,
    }


def guard_candidate_pois(
    candidate_pois: list[dict[str, Any]],
    request_payload: dict[str, Any],
    persona: dict[str, Any],
    weather: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from backend.planning.planning_profile import resolve_planning_profile

    passed: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for poi in candidate_pois:
        audit = evaluate_candidate_match(poi, request_payload, persona, weather)
        enriched = dict(poi)
        enriched["constraint_score"] = audit["score"]
        enriched["match_reasons"] = audit["reasons"]
        enriched["match_warnings"] = audit["warnings"]
        enriched["preference_hit"] = audit["preference_hit"]
        enriched["matched_preference_tags"] = audit["matched_preference_tags"]
        enriched["canonical_tags"] = audit["canonical_tags"]
        enriched["hard_block"] = audit["hard_block"]
        if audit["is_match"]:
            passed.append(enriched)
        else:
            dropped.append(enriched)

    from backend.planning.style_affinity import enrich_with_style_affinity, rank_by_style_affinity

    strict_mode = strict_style_mode(persona)
    days = int(request_payload.get("days", 3) or 3)
    planning_profile = resolve_planning_profile(persona, days=days)
    for poi in passed:
        enrich_with_style_affinity(poi, persona)
    for poi in dropped:
        enrich_with_style_affinity(poi, persona)

    min_affinity = 38.0 if strict_mode else 30.0
    ranked_passed = rank_by_style_affinity(passed, persona, min_affinity=min_affinity)
    if len(ranked_passed) < planning_profile.candidate_expansion_threshold:
        ranked_passed = rank_by_style_affinity(passed, persona, min_affinity=24.0)

    min_keep = min(planning_profile.candidate_guardrail, len(passed))
    if len(ranked_passed) < min_keep:
        supplement_pool = [item for item in dropped if not item.get("hard_block") and not item.get("style_veto")]
        supplement = rank_by_style_affinity(supplement_pool, persona, min_affinity=20.0)
        seen = {str(p.get("name", "")) for p in ranked_passed}
        for item in supplement:
            if len(ranked_passed) >= min_keep:
                break
            key = str(item.get("name", ""))
            if key and key not in seen:
                ranked_passed.append(item)
                seen.add(key)
    if len(ranked_passed) < min_keep:
        seen = {str(p.get("name", "")) for p in ranked_passed}
        fallback = rank_by_style_affinity(passed, persona, min_affinity=0.0)
        for item in fallback:
            if len(ranked_passed) >= min_keep:
                break
            key = str(item.get("name", ""))
            if key and key not in seen:
                ranked_passed.append(item)
                seen.add(key)

    preference_hits = [poi for poi in ranked_passed if poi.get("preference_hit")]

    guard = {
        "input_count": len(candidate_pois),
        "kept_count": len(ranked_passed),
        "dropped_count": len(dropped),
        "preferred_hit_count": len(preference_hits),
        "strict_mode": strict_mode,
        "summary": "已按偏好、预算、天气、体力和地理距离过滤候选景点。",
        "top_dropped": [
            {
                "name": poi.get("name", ""),
                "warnings": poi.get("match_warnings", []),
            }
            for poi in dropped[:5]
        ],
    }
    return ranked_passed, guard


def itinerary_match_summary(plan: dict[str, Any], persona: dict[str, Any]) -> dict[str, Any]:
    itinerary = plan.get("itinerary", []) or []
    preferred = preferred_tags(persona)
    total_points = 0
    matched_points = 0
    mismatched: list[str] = []

    for day in itinerary:
        for point in day.get("route_waypoints", []):
            total_points += 1
            tags = canonical_tags_from_text(
                point.get("name", ""),
                point.get("type", ""),
                point.get("knowledge_tags", []),
            )
            if preferred and tags & preferred:
                matched_points += 1
            elif not preferred:
                matched_points += 1
            else:
                mismatched.append(str(point.get("name", "未命名景点")))

    ratio = matched_points / total_points if total_points else 0.0
    return {
        "matched_points": matched_points,
        "total_points": total_points,
        "match_ratio": round(ratio, 2),
        "mismatched_points": mismatched[:6],
    }
