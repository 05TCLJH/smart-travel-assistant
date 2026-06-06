"""预算、审查与出行提示辅助函数。"""

from __future__ import annotations

import math
from typing import Any

from backend.planning.activity_load import day_load_used, resolve_daily_load_budget
from backend.planning.budget_style import budget_style_factor, normalize_budget_style
from backend.tools.grounding_tools import itinerary_match_summary, normalize_poi_tags, preferred_tags


def _parse_lnglat(raw: str) -> tuple[float, float] | None:
    text = str(raw or "").strip()
    if "," not in text:
        return None
    try:
        lng, lat = text.split(",", 1)
        return float(lng), float(lat)
    except ValueError:
        return None


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lng1, lat1 = a
    lng2, lat2 = b
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1 - h)))


def _plan_spread_summary(plan: dict[str, Any]) -> tuple[set[str], float]:
    cities: set[str] = set()
    points: list[tuple[float, float]] = []
    for day in plan.get("itinerary", []) or []:
        for point in day.get("route_waypoints", []) or []:
            city = str(point.get("city", "")).strip()
            if city:
                cities.add(city)
            location = _parse_lnglat(point.get("location", ""))
            if location:
                points.append(location)

    max_distance = 0.0
    for index, point in enumerate(points):
        for other in points[index + 1 :]:
            max_distance = max(max_distance, _distance_km(point, other))
    return cities, round(max_distance, 1)


def _day_route_spread_km(day: dict[str, Any]) -> float:
    points = [
        location
        for point in (day.get("route_waypoints", []) or [])
        if (location := _parse_lnglat(point.get("location", "")))
    ]
    max_distance = 0.0
    for index, point in enumerate(points):
        for other in points[index + 1 :]:
            max_distance = max(max_distance, _distance_km(point, other))
    return round(max_distance, 1)


def _plan_has_outdoor_or_remote(plan: dict[str, Any]) -> tuple[bool, bool]:
    has_outdoor = False
    has_remote_day = False
    for day in plan.get("itinerary", []) or []:
        if _day_route_spread_km(day) >= 25:
            has_remote_day = True
        for point in day.get("route_waypoints", []) or []:
            tags = normalize_poi_tags(point)
            name = str(point.get("name", "") or "")
            type_text = str(point.get("type", "") or "")
            if "nature" in tags or any(token in f"{name} {type_text}" for token in ("山", "草原", "峡谷", "森林", "湿地", "湖", "徒步")):
                has_outdoor = True
            if float(point.get("distance_to_destination_km", 0.0) or 0.0) >= 25:
                has_remote_day = True
    return has_outdoor, has_remote_day


def _destination_region_key(destination: str, plan: dict[str, Any]) -> str:
    haystack = destination + " " + " ".join(
        str(point.get(key, "") or "")
        for day in plan.get("itinerary", []) or []
        for point in day.get("route_waypoints", []) or []
        for key in ("province", "city", "district", "address", "name")
    )
    if any(token in haystack for token in ("新疆", "乌鲁木齐", "伊犁", "喀什", "阿勒泰")):
        return "xinjiang"
    if any(token in haystack for token in ("西藏", "拉萨", "日喀则", "林芝", "山南")):
        return "tibet"
    if any(token in haystack for token in ("青海", "甘肃", "内蒙古", "宁夏")):
        return "northwest"
    return ""


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _format_day_span(start_day: int, end_day: int) -> str:
    return f"Day {start_day}" if start_day == end_day else f"Day {start_day}-{end_day}"


def _primary_lodging_segments(
    lodgings: list[dict[str, Any]] | None,
    daily_stays: list[dict[str, Any]] | None,
) -> list[str]:
    primary = [
        hotel
        for hotel in (lodgings or [])
        if isinstance(hotel, dict) and (hotel.get("is_primary") or hotel.get("recommended_days"))
    ]
    if primary:
        return [
            f"{str(hotel.get('stay_label', '')).strip() or '部分天数'} 住在 {str(hotel.get('name', '')).strip() or '该片区酒店'}"
            for hotel in primary
        ]

    stays = [item for item in (daily_stays or []) if isinstance(item, dict) and str(item.get("hotel_name", "")).strip()]
    if not stays:
        return []
    segments: list[str] = []
    start_day = int(stays[0].get("day", 1) or 1)
    end_day = start_day
    current_name = str(stays[0].get("hotel_name", "")).strip()
    for stay in stays[1:]:
        day = int(stay.get("day", end_day + 1) or (end_day + 1))
        name = str(stay.get("hotel_name", "")).strip()
        if name == current_name and day == end_day + 1:
            end_day = day
            continue
        segments.append(f"{_format_day_span(start_day, end_day)} 住在 {current_name}")
        start_day = end_day = day
        current_name = name
    segments.append(f"{_format_day_span(start_day, end_day)} 住在 {current_name}")
    return segments


def _build_hotel_tip(
    plan: dict[str, Any],
    request_payload: dict[str, Any],
    transport_plan: dict[str, Any] | None,
    lodgings: list[dict[str, Any]] | None,
) -> dict[str, str] | None:
    itinerary = list((plan or {}).get("itinerary", []) or [])
    if not itinerary:
        return None

    daily_stays = [item for item in ((transport_plan or {}).get("daily_stays", []) or []) if isinstance(item, dict)]
    stay_segments = _primary_lodging_segments(lodgings, daily_stays)
    unique_hotels = _ordered_unique([str(item.get("hotel_name", "")).strip() for item in daily_stays])
    first_poi = next(
        (
            str(point).strip()
            for day in itinerary
            for point in (day.get("route_points", []) or [])
            if str(point).strip()
        ),
        "第一站",
    )
    last_poi = next(
        (
            str(point).strip()
            for day in reversed(itinerary)
            for point in reversed(day.get("route_points", []) or [])
            if str(point).strip()
        ),
        "最后一站",
    )
    max_day_hotel_distance = max(
        (
            float(item.get("distance_to_day_center_km") or 0.0)
            for item in daily_stays
            if item.get("distance_to_day_center_km") is not None
        ),
        default=0.0,
    )
    _, spread_km = _plan_spread_summary(plan)
    destination = str(request_payload.get("destination", "") or "").strip() or "目的地"

    if len(unique_hotels) >= 2:
        segment_text = "；".join(stay_segments[:3]) if stay_segments else "前后半程分段住"
        return {
            "tag": "住宿",
            "title": "这趟更适合分段住，别让一间酒店硬扛全程",
            "body": (
                f"这版动线从 {first_poi} 一路走到 {last_poi}，活动落点已经明显分开，按现在这样 {segment_text}，"
                "通常会比每天往返同一片更省折返。订房时先把每天首站和终点标到地图上，优先选当晚终点到次日首站之间、"
                "公共交通或打车都顺的位置；地铁口步行 5 到 10 分钟、楼下有便利店和早餐店，比单纯贴着景区门口更实用。"
                "景区正中心、高架旁、夜市正旁和偏僻小路尽量避开，省下的房费很容易被噪音和打车时间抵消。"
            ),
            "tone": "warm",
            "layout": "featured",
        }

    if spread_km >= 30 or max_day_hotel_distance >= 5.5:
        return {
            "tag": "住宿",
            "title": "如果最后只住一处，先按路线中心点找酒店",
            "body": (
                f"{destination} 这趟每天活动范围拉得不算窄，找房别只盯着某一个景点门口。更稳的做法是先把 {first_poi} 到 {last_poi} "
                "这条主线放到地图上，优先选多个景点的几何中点或地铁/公交换乘更顺的片区；短途陌生城市优先市中心或景区附近地铁站 500 米内，"
                "长天数想省钱再考虑主城地铁沿线。最后一晚如果要赶高铁或飞机，再单独挪到车站/机场附近。"
            ),
            "tone": "warm",
            "layout": "featured",
        }

    return {
        "tag": "住宿",
        "title": "这次景点相对集中，住交通顺手的片区会更省心",
        "body": (
            f"这版行程大多围绕 {first_poi} 一线展开，住同一片通常比天天搬酒店更轻松。选房时别只看离景点近，"
            "更建议优先挑地铁站 500 米内、便利店和早餐店齐全的位置；想吃美食就住老牌美食街区后街，不贴主街，既少噪音也不容易被游客价坑到。"
        ),
        "tone": "soft",
        "layout": "featured",
    }


def _estimate_ticket_line(point: dict[str, Any], companions: int, destination: str = "") -> dict[str, Any]:
    """为单个停靠点构建仅估算票价的条目。"""
    companions = max(1, companions)
    point_type = str(point.get("type", ""))
    name = str(point.get("name", ""))
    estimate_disclaimer = "以上均为经验估算，正式出发前请自行查看景区官方公告、预约页或正规售票平台。"

    if any(token in point_type for token in ("公园", "步行街")) or any(token in name for token in ("古街", "老街", "夜市")):
        return {
            "amount": 0.0,
            "note": "按开放式街区或城市公园估算为 0 元，实际仍请以景区当天公告为准。",
            "source_label": "经验估算",
            "source_type": "estimated",
            "source_name": "",
            "source_url": "",
            "unit_price": 0.0,
            "verification_hint": "免费开放场所也可能存在预约、联票或临时收费活动，请出发前自行确认。",
            "last_verified_at": "",
        }
    if "风景名胜" in point_type or "景区" in point_type:
        return {
            "amount": round(95.0 * companions, 0),
            "note": "按热门收费景区的常见成人票位估算，未计入索道、观光车、联票等附加项目。",
            "source_label": "经验估算",
            "source_type": "estimated",
            "source_name": "",
            "source_url": "",
            "unit_price": 95.0,
            "verification_hint": estimate_disclaimer,
            "last_verified_at": "",
        }
    if "博物馆" in point_type:
        return {
            "amount": round(38.0 * companions, 0),
            "note": "按专题馆、特展馆或预约制场馆的常见票位估算，免费馆也可能出现特展单收费。",
            "source_label": "经验估算",
            "source_type": "estimated",
            "source_name": "",
            "source_url": "",
            "unit_price": 38.0,
            "verification_hint": estimate_disclaimer,
            "last_verified_at": "",
        }
    return {
        "amount": round(58.0 * companions, 0),
        "note": "按综合景点的常见票位估算，实际价格可能随日期、票种和优惠政策变化。",
        "source_label": "经验估算",
        "source_type": "estimated",
        "source_name": "",
        "source_url": "",
        "unit_price": 58.0,
        "verification_hint": estimate_disclaimer,
        "last_verified_at": "",
    }


def build_budget_breakdown(request_payload: dict[str, Any], persona: dict[str, Any], itinerary: list[dict[str, Any]]) -> dict[str, Any]:
    days = max(1, int(request_payload["days"]))
    budget = float(request_payload["budget"])
    companions = max(1, int(persona.get("companions", 1) or 1))
    style = normalize_budget_style(persona.get("budget_style"))
    style_factor = budget_style_factor(style)

    lodging = 220.0 * days * max(1, math.ceil(companions / 2)) * style_factor
    lodging_lines = [
        {
            "label": "住宿档位",
            "detail": f"{days} 晚 ·「{style}」画像对应的酒店/民宿均价估算（按一间房约住 2 人折算房间数）。",
            "amount": round(lodging, 0),
            "source_label": "预测",
            "source_type": "predicted",
        }
    ]

    meals = 70.0 * days * companions * style_factor
    meal_lines = [
        {
            "label": "餐饮",
            "detail": f"{days} 天 × {companions} 人 × 日均正餐小吃合计（「{style}」系数已计入）。",
            "amount": round(meals, 0),
            "source_label": "预测",
            "source_type": "predicted",
        }
    ]

    taxi_pref = "打车" in str(persona.get("transport_preference", ""))
    transport = 55.0 * days * companions if taxi_pref else 22.0 * days * companions
    transport_lines = [
        {
            "label": "市内接驳",
            "detail": "景点之间打车/网约车为主的短途接驳估算。"
            if taxi_pref
            else "以公共交通为主的市内接驳估算（不含往返大交通）。",
            "amount": round(transport, 0),
            "source_label": "预测",
            "source_type": "predicted",
        }
    ]

    ticket_lines: list[dict[str, Any]] = []
    tickets = 0.0
    for day_idx, day in enumerate(itinerary, start=1):
        for point in day.get("route_waypoints", []) or []:
            ticket_info = _estimate_ticket_line(point, companions, str(request_payload.get("destination", "")).strip())
            amt = float(ticket_info.get("amount") or 0.0)
            tickets += amt
            ticket_lines.append(
                {
                    "day": day_idx,
                    "place": str(point.get("name", "") or "景点"),
                    "amount": amt,
                    "note": str(ticket_info.get("note", "")).strip(),
                    "source_label": str(ticket_info.get("source_label", "经验估算")).strip(),
                    "source_type": str(ticket_info.get("source_type", "estimated")).strip(),
                    "source_name": str(ticket_info.get("source_name", "")).strip(),
                    "source_url": str(ticket_info.get("source_url", "")).strip(),
                    "unit_price": float(ticket_info.get("unit_price") or 0.0),
                    "verification_hint": str(ticket_info.get("verification_hint", "")).strip(),
                    "last_verified_at": str(ticket_info.get("last_verified_at", "")).strip(),
                }
            )

    floating = max((lodging + meals + transport + tickets) * 0.12, 80.0)
    floating_lines = [
        {
            "label": "机动金",
            "detail": "预留打车加价、零食饮品、临时改签与小额零售；约为前述刚性支出的 12%。",
            "amount": round(floating, 0),
            "source_label": "预测",
            "source_type": "predicted",
        }
    ]

    raw = {"住宿": lodging, "餐饮": meals, "市内交通": transport, "门票/预约": tickets, "机动": floating}
    total_before_cap = sum(raw.values())
    ratio = 1.0
    if budget > 0 and total_before_cap > budget:
        scalable_total = lodging + meals + transport + tickets + floating
        ratio = min(1.0, budget / scalable_total) if scalable_total > 0 else 1.0
        raw = {
            "住宿": lodging * ratio,
            "餐饮": meals * ratio,
            "市内交通": transport * ratio,
            "门票/预约": 0.0,
            "机动": floating * ratio,
        }
        lodging_lines[0]["amount"] = round(raw["住宿"], 0)
        meal_lines[0]["amount"] = round(raw["餐饮"], 0)
        transport_lines[0]["amount"] = round(raw["市内交通"], 0)
        floating_lines[0]["amount"] = round(raw["机动"], 0)
        for row in ticket_lines:
            row["amount"] = round(float(row["amount"]) * ratio, 0)
            raw["门票/预约"] += float(row["amount"] or 0.0)

    breakdown = {key: round(value, 0) for key, value in raw.items()}
    estimate_count = len(ticket_lines)
    budget_note = (
        f"按 {companions} 人、`{style}` 档位估算；当前共纳入 {estimate_count} 个门票/预约点位，所有门票金额都只是预算估算值。"
        " 实际出发前，请逐个景点自行查看官方预约页、景区公告或正规售票平台。"
    )
    if ratio < 1.0:
        budget_note += f" 为尽量贴近总预算 {int(budget)} 元，系统已同步压缩住宿、餐饮、交通和门票的估算强度。"

    return {
        "estimated_total_cost": round(sum(float(value) for value in breakdown.values()), 0),
        "cost_breakdown": breakdown,
        "budget_note": budget_note,
        "budget_detail": {
            "lodging": {"total": breakdown["住宿"], "lines": lodging_lines},
            "meals": {"total": breakdown["餐饮"], "lines": meal_lines},
            "transport": {"total": breakdown["市内交通"], "lines": transport_lines},
            "tickets": {
                "total": breakdown["门票/预约"],
                "lines": ticket_lines,
                "summary": {
                    "official_price_count": 0,
                    "live_price_count": 0,
                    "platform_live_price_count": 0,
                    "estimated_count": estimate_count,
                    "official_places": [],
                    "verified_places": [],
                    "platform_live_places": [],
                    "estimated_places": [row["place"] for row in ticket_lines],
                },
            },
            "buffer": {"total": breakdown["机动"], "lines": floating_lines},
        },
    }


def review_plan(request_payload: dict[str, Any], persona: dict[str, Any], weather: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    issue_codes: list[str] = []
    itinerary = plan.get("itinerary", []) or []

    def add_issue(code: str, message: str) -> None:
        if code not in issue_codes:
            issue_codes.append(code)
        issues.append(message)

    if not any(day.get("route_points") for day in itinerary):
        add_issue("no_valid_itinerary", "没有生成有效路线")

    if (plan.get("estimated_total_cost") or 0) > (request_payload.get("budget") or 0) * 1.05:
        add_issue("budget_exceeded", "总预算超出用户要求")

    if weather.get("rating") == "较差":
        outdoor_points = 0
        for day in itinerary:
            for point in day.get("route_waypoints", []):
                tags = normalize_poi_tags(point)
                if "nature" in tags:
                    outdoor_points += 1
        if outdoor_points >= max(2, len(itinerary)):
            add_issue("bad_weather_outdoor_heavy", "恶劣天气下户外景点占比过高")

    from backend.planning.stamina_profile import normalize_stamina, resolve_stamina_profile

    stamina = normalize_stamina(persona.get("stamina", "适中"))
    profile = resolve_stamina_profile(persona)
    daily_budget = resolve_daily_load_budget(persona, plan.get("routing_policy"))
    for day in itinerary:
        points = day.get("route_points", []) or []
        used = int(day.get("activity_load_used") or 0)
        if not used and points:
            used = day_load_used(day.get("route_waypoints", []) or [])
        if used > daily_budget + 8:
            add_issue("day_overloaded", f"Day {day.get('day', '?')} 活动负荷偏高，超出当前体力节奏")
        if any(
            wp.get("activity_load", 0) >= 90 or "整日" in str(wp.get("activity_tier_label", ""))
            for wp in (day.get("route_waypoints", []) or [])
        ) and len(points) > 1:
            add_issue("full_day_conflict", f"Day {day.get('day', '?')} 含整日级景点，不宜再叠加多个主力点")
        if points and len(points) < profile.min_pois_per_day and used < int(daily_budget * profile.min_day_load_ratio):
            add_issue(
                "day_underfilled",
                f"Day {day.get('day', '?')} 景点过少或有效游览偏短，与「{profile.key}」体力不匹配"
            )

    if stamina == "轻松":
        overloaded = [day for day in itinerary if len(day.get("route_points", [])) > 2]
        if overloaded:
            add_issue("light_stamina_overpacked", "当前体力画像偏弱，但单日景点数量偏多")
        heavy_days = [
            day
            for day in itinerary
            if int(day.get("activity_load_used") or 0) > min(daily_budget, 80)
        ]
        if heavy_days:
            add_issue("light_stamina_overload", "轻松体力下部分单日活动负荷仍偏高，建议减少户外登山或拆日")

    match_summary = itinerary_match_summary(plan, persona)
    preferred = preferred_tags(persona)
    min_ratio = 0.7 if preferred else 0.45
    if match_summary["total_points"] and match_summary["match_ratio"] < min_ratio:
        add_issue("preference_mismatch", "当前路线与用户核心偏好贴合度不足")

    routing_hint = "planning" if issues else "finalize"

    return {
        "passed": not issues,
        "issues": issues,
        "issue_codes": issue_codes,
        "routing_hint": routing_hint,
        "next_step": routing_hint,
        "provider": "budget-review-agent",
        "match_summary": match_summary,
        "summary": "方案满足当前用户约束。" if not issues else "方案需要根据审查意见继续修正。",
    }


def build_reflection(plan: dict[str, Any], review_feedback: dict[str, Any]) -> dict[str, Any]:
    issues = list(review_feedback.get("issues", []) or [])
    return {
        "passed": not issues,
        "issues": issues,
        "repair_instruction": "请优先根据预算、天气、体力和偏好贴合度调整路线。" if issues else "",
        "provider": "langgraph-review-agent",
    }


def build_tips(
    weather: dict[str, Any],
    plan: dict[str, Any],
    request_payload: dict[str, Any],
    persona: dict[str, Any],
    transport_plan: dict[str, Any] | None = None,
    lodgings: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    destination = str(request_payload.get("destination", "") or "").strip() or "目的地"
    days = max(1, int(request_payload.get("days") or 1))
    start_date = str(request_payload.get("start_date", "") or "").strip()
    from backend.planning.stamina_profile import normalize_stamina

    stamina = normalize_stamina(persona.get("stamina", "适中"))
    companions = max(1, int(persona.get("companions", 1) or 1))

    highlights: list[str] = []
    for day in (plan.get("itinerary", []) or [])[: days + 2]:
        for point in (day.get("route_waypoints", []) or [])[:3]:
            name = str(point.get("name", "") or "").strip()
            if name and name not in highlights:
                highlights.append(name)

    preview = "、".join(highlights[:5]) if highlights else "目的地节奏"
    itinerary = plan.get("itinerary", []) or []
    first_day_points = []
    if itinerary:
        first_day_points = [str(name).strip() for name in (itinerary[0].get("route_points", []) or []) if str(name).strip()]

    def tip_card(tag: str, title: str, body: str, tone: str = "soft", layout: str = "default") -> dict[str, str]:
        return {
            "tag": tag,
            "title": title,
            "body": body,
            "tone": tone,
            "layout": layout,
        }

    tips: list[dict[str, str]] = []

    if weather.get("is_fallback"):
        warn = str(weather.get("warning", "") or "").strip()
        tips.append(
            tip_card(
                "天气",
                "出发前一晚，再看一次实时天气",
                f"{destination} 的在线天气目前还没完全接上{'，原因是' + warn if warn else ''}。"
                f"界面里的温度和晴雨先当作方向感参考，真正打包衣服时，记得用手机天气再确认一遍。",
                "alert",
            )
        )
    else:
        tips.append(
            tip_card(
                "天气",
                "把第二天要穿的衣服提前搭好，会轻松很多",
                f"{destination} 当前天气评级是「{weather.get('rating', '未知')}」。"
                f"如果这趟里有山、水或傍晚慢逛的安排，建议临行前 24 小时再刷新一次短时预报，包里顺手塞一件轻外套，心里会更踏实。",
                "soft",
            )
        )

    has_outdoor, has_remote_day = _plan_has_outdoor_or_remote(plan)
    region_key = _destination_region_key(destination, plan)
    if region_key == "xinjiang":
        tips.append(
            tip_card(
                "新疆",
                "把新疆按“晚两小时、远很多、晒更狠”来准备",
                (
                    f"{destination} 行程里{'有远郊/自然景点' if has_outdoor or has_remote_day else '以市区点为主'}，时间别按内地城市游卡太死。"
                    "白天紫外线强、昼夜温差大，山区或草原傍晚要备防风外套；身份证随身放，商场、景区、车站安检都会用到。"
                    "吃饭时间通常整体后移，午餐别太早冲，晚餐和夜市反而可以从容一点。"
                ),
                "alert" if has_remote_day else "warm",
            )
        )
        if has_remote_day or has_outdoor:
            tips.append(
                tip_card(
                    "交通",
                    "新疆远郊点先定返程方式，再决定要不要加景点",
                    "南山、草原、峡谷这类点公共交通往往不稳定，包车/拼车/自驾要比临时打车可靠；山区信号和补给都可能变弱，离线地图、水、防晒和少量现金最好提前备好。",
                    "alert",
                )
            )
    elif region_key == "tibet":
        tips.append(
            tip_card(
                "高原",
                "西藏行程宁可慢半拍，也别第一天就拉满",
                "刚到高原先把节奏放轻，少跑跳、少饮酒，多喝水；寺庙和宫殿类点常有安检、预约和限流，身份证件、保暖层和防晒都要随身。若出现明显不适，优先休息而不是硬赶下一站。",
                "alert",
            )
        )
    elif has_outdoor or has_remote_day:
        tips.append(
            tip_card(
                "户外",
                "远郊自然景点按半日以上准备，别只看地图直线距离",
                "山地、湿地、森林、草原和峡谷类点，真正耗时通常在进出景区、步道、观光车/摆渡车和返程上。当天最好少加主力点，提前看末班车或返程打车可用性，包里备水和轻外套。",
                "warm",
            )
        )

    if start_date:
        rhythm_body = f"这次从 {start_date} 出发，一共 {days} 天，主线已经围绕 {preview} 串好了。"
    else:
        rhythm_body = f"这次行程按 {days} 天铺开，主线会围绕 {preview} 慢慢展开。"
    if first_day_points:
        rhythm_body += f"第一天先从 {first_day_points[0]} 开场" + (
            f"，再顺着走到 {first_day_points[1]}" if len(first_day_points) > 1 else ""
        ) + "，节奏更容易进入状态。"
    rhythm_body += " 真到了现场，不必把每个点都卡满时长，遇到特别喜欢的地方，多停半小时往往比赶下一个点更值。"
    tips.append(tip_card("节奏", "把喜欢的地方留出一点停顿，行程会更有味道", rhythm_body, "warm"))

    hotel_tip = _build_hotel_tip(plan, request_payload, transport_plan, lodgings)
    if hotel_tip:
        tips.append(hotel_tip)

    stamina = normalize_stamina(stamina)
    if stamina == "轻松":
        tips.append(
            tip_card(
                "体力",
                "中午那段空白，不是浪费，是给下午留兴致",
                "这版节奏更适合慢慢看。午后真觉得累时，找家顺眼的小店坐一会儿、喝点热的，再去下一站，往往比硬塞一个景点更舒服。",
                "soft",
            )
        )
    elif stamina == "充沛":
        tips.append(
            tip_card(
                "体力",
                "如果当天收得早，把好时段留给傍晚",
                "你这趟完全有余力把白天省下来的时间，换成观景台的日落、临江散步或者夜市慢逛。那一段往往最容易留下旅行的氛围感。",
                "warm",
            )
        )

    ticket_hint_parts = [
        "预算里的门票数字主要用来帮助你看整体花费轮廓，并不代表系统已经替你查到实时售价",
        "同一个景区真正容易拉开花费的，通常是联票、索道、摆渡车、夜场票和分时预约要求",
    ]
    tips.append(
        tip_card(
            "门票",
            "门票别只看数字，更要看它是不是含索道、摆渡车和预约名额",
            "；".join(ticket_hint_parts) + "。同一个景区里，真正拉开花费的，往往不是大门票本身，而是联票、索道和园内接驳。",
            "alert",
        )
    )

    tips.append(
        tip_card(
            "预约",
            "热门景区尽量前一晚把预约和入园时段一起定掉",
            "旺季时最耽误心情的，往往不是排队本身，而是到了门口才发现要实名预约、分时入园，或者索道和观光车需要单独排队。"
            "把这一步提前做掉，第二天会轻松很多。",
            "alert",
        )
    )

    meal_body = "每天至少留一顿饭给自己慢慢吃，不必总挤在景点前后匆忙解决。旅行里真正让人放松下来的，常常就是那顿坐定了吃的饭。"
    tips.append(tip_card("吃饭", "吃饭和休息安排顺了，一整天的体验会稳很多", meal_body, "soft"))

    transport_body = "高峰期给接驳多留 15 到 25 分钟，心态会从容很多；如果有偏远观景台或夜间返程，最好提前把回程方式也想好。"
    cities, spread_km = _plan_spread_summary(plan)
    if len(cities) > 1 or spread_km >= 35:
        transport_body += " 这版动线拉得稍微有点开，临时跨城加点很容易把当天节奏打散，最好谨慎加戏。"
    tips.append(tip_card("交通", "回程别等走累了再想，尤其是傍晚那一段", transport_body, "soft"))

    if companions > 1:
        tips.append(
            tip_card(
                "同行",
                "多人同行时，把‘谁来决定下一站’提前说好，会省掉很多小摩擦",
                f"这次按 {companions} 人一起核了预算。住宿和打车其实都比较好分摊，真正容易拖慢节奏的，往往是现场临时改主意，提前说好谁来拍板会更顺。",
                "warm",
            )
        )

    if any(item.get("is_pending") for item in weather.get("daily", []) or []):
        tips.append(
            tip_card(
                "临行前",
                "出发那周，再把天气和开放信息复核一遍",
                "有几天的天气还在等后续更新。真正临近出发时，再看一次天气、开放时间和预约状态，能帮你避开大部分临场慌乱。",
                "alert",
            )
        )

    return tips[:8]
