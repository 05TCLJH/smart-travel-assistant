"""景点活动负荷：估算单次游览耗时/体力，驱动按日分配与时间轴。

负荷单位以「一日有效游览容量 = 100」为基准（非 POI 个数）。
下游规划应优先看 daily_activity_load_budget，max_pois_per_day 仅作硬上限兜底。
"""

from __future__ import annotations

import re
from typing import Any

from backend.tools.grounding_tools import normalize_poi_tags

# 100 ≈ 一日主力活动时间（不含长途交通）
LOAD_LIGHT = 22
LOAD_STANDARD = 38
LOAD_EXTENDED = 52
LOAD_HALF_DAY = 72
LOAD_FULL_DAY = 95

TIER_LABELS = {
    "light": "轻量",
    "standard": "常规",
    "extended": "深度",
    "half_day": "半日",
    "full_day": "整日",
}

# ---------- 负荷分级词表（名称 + 类型文本匹配，长词优先）----------

# 整日级：单次游览通常占满白天，不宜再叠其它主力点
FULL_DAY_MARKERS = (
    # 自然保护地 / 大尺度地貌
    "国家森林公园",
    "国家地质公园",
    "国家级风景名胜区",
    "国家湿地公园",
    "世界自然遗产",
    "世界遗产",
    "自然保护区",
    "风景名胜区",
    "风景旅游区",
    "大峡谷",
    "大峡谷景区",
    "大草原",
    "空中草原",
    "高原草原",
    "沙漠公园",
    "沙漠景区",
    "盐湖",
    "天坑",
    "地缝",
    "溶洞景区",
    "瀑布群",
    "冰川",
    "雪山",
    "雪山景区",
    "高原",
    "高原景区",
    # 山岳型景区（独立出现时也常是一日行程）
    "登山",
    "登顶",
    "索道",
    "缆车",
    "栈道",
    "天梯",
    "玻璃栈道",
    "天空步道",
    # 户外体验（通常耗时半日以上）
    "徒步",
    "穿越",
    "溯溪",
    "攀岩",
    "漂流",
    "滑雪场",
    "滑雪度假区",
    "滑雪度假村",
    "滑翔伞",
    "跳伞",
    "骑马",
    "越野",
    "露营基地",
    # 知名大景区 / 环线品牌词
    "国家公园",
    "森林公园",
    "生态旅游",
    "环湖",
    "环线",
    "大峡谷漂流",
    "草原景区",
    "草原风景区",
)

# 地貌锚词 + 景区通名（如「武功山风景名胜区」「喀纳斯湖景区」）
FULL_DAY_GEO_SCENIC: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("山", ("景区", "风景区", "风景名胜区", "国家公园", "森林公园", "步道", "登山", "滑雪", "草原", "大峡谷")),
    ("峰", ("景区", "风景区", "风景名胜区", "国家森林公园", "国家公园")),
    ("岭", ("景区", "风景区", "国家森林公园", "国家公园", "草原")),
    ("顶", ("景区", "风景区", "登山", "观景")),
    ("峡", ("景区", "风景区", "大峡谷", "地质公园", "漂流")),
    ("谷", ("景区", "风景区", "森林公园", "漂流", "地缝")),
    ("洞", ("景区", "风景区", "地质公园", "溶洞", "漂流")),
    ("瀑", ("景区", "风景区", "瀑布", "大峡谷")),
    ("湖", ("风景名胜区", "风景区", "景区", "国家公园", "湿地公园", "生态旅游")),
    ("海", ("景区", "风景区", "公园", "生态旅游")),
    ("岛", ("景区", "风景区", "公园")),
    ("草原", ("景区", "风景区", "国家公园", "空中草原", "大草原", "生态旅游")),
    ("沙漠", ("景区", "旅游区", "公园", "越野")),
    ("湿地", ("国家公园", "自然保护区", "风景区", "景区")),
    ("江", ("大峡谷", "风景区", "景区", "漂流")),
    ("河", ("大峡谷", "风景区", "景区", "漂流", "古道")),
)

# 半日级：至少 3–5 小时，当天通常只宜 1 个为主 + 可选 1 个轻量点
HALF_DAY_MARKERS = (
    # 古镇古城 / 历史街区
    "古镇",
    "古城",
    "古村",
    "古寨",
    "古街",
    "历史街区",
    "历史文化街区",
    "民俗村",
    "民族村",
    "寨",
    # 动物园或度假区按半日处理；非主题乐园按 6 小时估算，主题乐园走专门形态规则
    "野生动物园",
    "动物园",
    "植物园",
    "旅游度假区",
    "度假区",
    "影视城",
    "影视基地",
    "科幻城",
    # 大型文博 / 遗址
    "博物院",
    "博物馆",
    "遗址公园",
    "遗址博物馆",
    "考古遗址",
    "陵墓",
    "陵寝",
    "皇宫",
    "故宫",
    "王宫",
    "王府",
    "城墙景区",
    "古城墙",
    # 大尺度水体 / 湿地游
    "湿地公园",
    "海洋世界",
    "海底世界",
    "水族馆",
    "游船",
    "轮渡",
    "观光船",
    # 综合园区
    "博览园",
    "博览区",
    "园博园",
    "世博园",
    "风情小镇",
    "风情街",
    "风情区",
    "文创园",
    "文旅小镇",
)

# 大型博物馆单独加权（在时长估算中可抬升为半日）
HALF_DAY_MUSEUM_MARKERS = (
    "省博物馆",
    "市博物馆",
    "国家博物馆",
    "中国博物馆",
    "历史博物馆",
    "革命博物馆",
    "纪念馆",
    "纪念园",
    "陈列馆",
    "美术馆",
    "艺术馆",
)

# 深度游：约 2.5–3.5 小时
EXTENDED_MARKERS = (
    "博物馆",
    "纪念堂",
    "故居",
    "旧居",
    "寺",
    "庙",
    "祠",
    "庵",
    "观",
    "塔",
    "阁",
    "楼",
    "陵",
    "墓",
    "书院",
    "文庙",
    "禅院",
    "石窟",
    "石刻",
    "碑林",
    "园林",
    "园",
    "公园",
    "湿地公园",
    "森林公园",
    "湿地",
    "步行街",
    "商业街",
    "巷",
    "坊",
    "里",
    "市场",
    "夜市",
    "老街",
)

# 轻量：约 1 小时以内，适合串联多个或作晚间点缀
LIGHT_MARKERS = (
    "广场",
    "塑像",
    "雕像",
    "纪念碑",
    "纪念亭",
    "牌楼",
    "牌坊",
    "门楼",
    "城门",
    "城楼",
    "观景台",
    "眺望台",
    "瞭望台",
    "驿站",
    "驿站遗址",
    "雕像园",
    "喷泉",
    "街心花园",
    "口袋公园",
    "社区公园",
    "滨江步道",
    "滨河绿道",
    "打卡点",
    "拍照点",
    "网红墙",
    "灯塔",
    "桥",
    "大桥观景",
)

# 附属设施：强制降为轻量（避免售票处/游客中心占满行程）
AUXILIARY_LOAD_MARKERS = (
    "游客中心",
    "售票处",
    "检票口",
    "东门",
    "西门",
    "南门",
    "北门",
    "停车场",
    "服务区",
    "出入口",
    "咨询处",

)


def _haystack(poi: dict[str, Any]) -> str:
    return " ".join(
        str(poi.get(key, "") or "")
        for key in ("name", "type", "address")
    )


def _match_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _match_geo_scenic(name: str) -> bool:
    if "风景名胜区" in name and _match_any(
        name,
        ("山", "峰", "岭", "峡", "谷", "湖", "海", "草原", "沙漠", "瀑布", "冰川", "雪山"),
    ):
        return True
    for anchor, suffixes in FULL_DAY_GEO_SCENIC:
        if anchor in name and any(suffix in name for suffix in suffixes):
            return True
    return False


def _load_to_tier(load: int) -> str:
    if load >= LOAD_FULL_DAY - 5:
        return "full_day"
    if load >= LOAD_HALF_DAY - 5:
        return "half_day"
    if load >= LOAD_EXTENDED - 5:
        return "extended"
    if load >= LOAD_STANDARD - 5:
        return "standard"
    return "light"


def _extract_typecodes(poi: dict[str, Any]) -> set[str]:
    raw = " ".join(
        str(poi.get(key, "") or "")
        for key in ("type", "typecode", "biz_type")
    )
    return {code for code in re.findall(r"\d{6}", raw) if code}


def _typecode_load_hint(poi: dict[str, Any]) -> tuple[int, str] | None:
    """高德 typecode 粗分级：在名称规则未命中时兜底抬升/压低。"""
    codes = _extract_typecodes(poi)
    type_text = str(poi.get("type", "")).strip()
    if not codes and not type_text:
        return None
    if codes & {"080501", "080502", "080503", "080504"} or "游乐园" in type_text or "主题乐园" in type_text:
        return LOAD_HALF_DAY, "half_day"
    if codes & {"140100", "140101", "140200"} or ("博物馆" in type_text and "纪念" not in type_text):
        name = str(poi.get("name", ""))
        if _match_any(name, HALF_DAY_MUSEUM_MARKERS) or len(name) >= 6:
            return LOAD_HALF_DAY, "half_day"
        return LOAD_EXTENDED, "extended"
    if codes & {"110200", "110201", "110202"} or "风景名胜" in type_text:
        name = str(poi.get("name", ""))
        if _match_geo_scenic(name) or _match_any(name, ("山", "峰", "岭", "峡", "谷", "草原", "瀑布", "雪山")):
            return LOAD_FULL_DAY, "full_day"
        if "国家级" in type_text or "世界遗产" in type_text:
            return LOAD_FULL_DAY, "full_day"
        return LOAD_EXTENDED, "extended"
    if codes & {"110100", "110101"} or ("公园" in type_text and "风景名胜" not in type_text):
        return LOAD_STANDARD, "standard"
    if codes & {"060100", "060101", "060102"} or "购物" in type_text:
        return LOAD_EXTENDED, "extended"
    return None


def _estimate_activity_load_rules(poi: dict[str, Any]) -> dict[str, Any]:
    """仅规则 + typecode：供 bootstrap 与无知识库场景。"""
    name = str(poi.get("name", "")).strip()
    text = _haystack(poi)
    type_text = str(poi.get("type", "")).strip()
    tags = set(poi.get("canonical_tags", []) or normalize_poi_tags(poi))
    load = LOAD_STANDARD
    tier = "standard"
    matched_rule = False

    from backend.planning.venue_archetype import is_auxiliary_facility, is_theme_park_poi

    if is_auxiliary_facility(name):
        load, tier = LOAD_LIGHT, "light"
        matched_rule = True
    elif is_theme_park_poi(name, type_text):
        load, tier = LOAD_HALF_DAY, "half_day"
        matched_rule = True
    elif _match_any(name, AUXILIARY_LOAD_MARKERS) and not _match_any(
        name,
        FULL_DAY_MARKERS + HALF_DAY_MARKERS,
    ):
        load, tier = LOAD_LIGHT, "light"
        matched_rule = True
    elif _match_any(text, FULL_DAY_MARKERS) or _match_geo_scenic(name):
        load, tier = LOAD_FULL_DAY, "full_day"
        matched_rule = True
    elif _match_any(text, HALF_DAY_MARKERS) or _match_any(name, HALF_DAY_MUSEUM_MARKERS):
        load, tier = LOAD_HALF_DAY, "half_day"
        matched_rule = True
    elif "nature" in tags and _match_any(
        name,
        ("山", "峰", "岭", "峡", "谷", "草原", "瀑布", "冰川", "沙漠", "雪山", "高原"),
    ):
        if _match_any(name, ("景区", "风景区", "风景名胜区", "国家公园", "森林公园", "大草原", "草原", "大峡谷")):
            load, tier = LOAD_FULL_DAY, "full_day"
        else:
            load, tier = LOAD_HALF_DAY, "half_day"
        matched_rule = True
    elif _match_any(text, EXTENDED_MARKERS):
        load, tier = LOAD_EXTENDED, "extended"
        matched_rule = True
        if _match_any(name, ("博物院", "博物馆")) and len(name) >= 6:
            load, tier = LOAD_HALF_DAY, "half_day"
        elif "寺" in name and any(token in name for token in ("寺", "庙", "禅院")) and len(name) <= 8:
            load, tier = LOAD_STANDARD, "standard"
    elif _match_any(text, LIGHT_MARKERS):
        load, tier = LOAD_LIGHT, "light"
        matched_rule = True
    elif "street" in tags or "历史文化" in type_text:
        # 街区漫游可同日串联 2 到 3 段，不宜按半日扩展负荷独占当天预算
        load, tier = LOAD_STANDARD, "standard"
        matched_rule = True
    elif "风景名胜" in type_text and "公园" not in name:
        load, tier = LOAD_EXTENDED, "extended"
        matched_rule = True

    if not matched_rule:
        hint = _typecode_load_hint(poi)
        if hint:
            load, tier = hint

    distance = float(poi.get("distance_to_destination_km", 0.0) or 0.0)
    if tier == "light":
        pass
    elif tier == "full_day" and distance > 40:
        load = LOAD_FULL_DAY
    elif tier not in {"full_day", "half_day"}:
        if distance > 35:
            load = min(LOAD_FULL_DAY, load + 18)
            tier = _load_to_tier(load)
        elif distance > 22:
            load = min(LOAD_HALF_DAY, load + 10)
            tier = _load_to_tier(load)

    from backend.planning.visit_duration import metrics_from_rules_payload

    if is_theme_park_poi(name, type_text):
        from backend.planning.venue_archetype import metrics_from_poi_archetype

        payload = metrics_from_poi_archetype(poi)
        payload["activity_load_source"] = "rules"
        return payload

    return metrics_from_rules_payload(
        {
            "activity_load": load,
            "activity_tier": tier,
            "activity_load_source": "rules",
        },
        poi,
    )


def estimate_activity_load(
    poi: dict[str, Any],
    *,
    visit_profiles: dict[str, dict[str, Any]] | None = None,
    destination: str | None = None,
) -> dict[str, Any]:
    """委托 venue_visit_resolver 统一解析（形态 → 知识库校准 → 规则兜底）。"""
    from backend.planning.venue_visit_resolver import resolve_poi_visit_metrics

    return resolve_poi_visit_metrics(
        poi,
        visit_profiles=visit_profiles,
        destination=destination,
    )


def enrich_poi_with_activity_load(
    poi: dict[str, Any],
    *,
    destination: str | None = None,
    visit_profiles: dict[str, dict[str, Any]] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    enriched = dict(poi)
    if (
        not force
        and enriched.get("activity_load_source") in ("knowledge", "rules")
        and enriched.get("activity_tier")
        and enriched.get("activity_load") is not None
    ):
        return enriched

    profiles = visit_profiles
    if profiles is None and destination:
        from backend.knowledge.destination_catalog import merged_visit_profiles_for_destination

        profiles = merged_visit_profiles_for_destination(destination)

    metrics = estimate_activity_load(enriched, visit_profiles=profiles, destination=destination)
    enriched.update(metrics)
    from backend.planning.poi_type_display import normalize_poi_type_label

    enriched["type_label"] = normalize_poi_type_label(
        str(enriched.get("type", "")),
        poi_name=str(enriched.get("name", "")),
    )
    return enriched


def default_daily_load_budget(stamina: str, day_pacing: str = "balanced") -> int:
    from backend.planning.stamina_profile import apply_pacing_adjustment, resolve_stamina_profile

    profile = resolve_stamina_profile({"stamina": stamina})
    return apply_pacing_adjustment(profile.daily_load_budget, day_pacing)


def resolve_daily_load_budget(
    persona: dict[str, Any] | None,
    routing_policy: dict[str, Any] | None = None,
) -> int:
    rp = routing_policy or {}
    persona = persona or {}
    if rp.get("daily_activity_load_budget") is not None:
        try:
            return max(60, min(int(rp["daily_activity_load_budget"]), 130))
        except (TypeError, ValueError):
            pass
    if persona.get("daily_activity_load_budget") is not None:
        try:
            return max(60, min(int(persona["daily_activity_load_budget"]), 130))
        except (TypeError, ValueError):
            pass
    return default_daily_load_budget(
        str(persona.get("stamina", "适中")),
        str(rp.get("day_pacing", "balanced")),
    )


def day_load_used(day_pois: list[dict[str, Any]]) -> int:
    return sum(int(p.get("activity_load", LOAD_STANDARD) or LOAD_STANDARD) for p in day_pois)


def is_full_day_poi(poi: dict[str, Any]) -> bool:
    return int(poi.get("activity_load", 0) or 0) >= LOAD_FULL_DAY - 5


def is_half_day_or_heavier(poi: dict[str, Any]) -> bool:
    return int(poi.get("activity_load", 0) or 0) >= LOAD_HALF_DAY - 5


BACKFILL_BUDGET_MARGIN = 20


def can_assign_poi_to_day(
    day_pois: list[dict[str, Any]],
    poi: dict[str, Any],
    daily_budget: int,
    max_pois_per_day: int,
    *,
    budget_margin: int = 0,
) -> bool:
    if len(day_pois) >= max_pois_per_day:
        return False

    load = int(poi.get("activity_load", LOAD_STANDARD) or LOAD_STANDARD)
    used = day_load_used(day_pois)

    if load >= LOAD_FULL_DAY - 5:
        return len(day_pois) == 0

    if any(is_full_day_poi(p) for p in day_pois):
        return False

    if load >= LOAD_HALF_DAY - 5:
        if any(is_half_day_or_heavier(p) for p in day_pois):
            return False
        if len(day_pois) >= 2:
            return False
        return used + load <= daily_budget + budget_margin

    if day_pois and any(is_half_day_or_heavier(p) for p in day_pois):
        if len(day_pois) >= 2:
            return False
        if load > LOAD_STANDARD and budget_margin <= 0:
            return False

    return used + load <= daily_budget + budget_margin


def _day_needs_backfill(
    day_pois: list[dict[str, Any]],
    daily_budget: int,
    min_pois: int,
    min_ratio: float,
) -> bool:
    if len(day_pois) < min_pois:
        return True
    if not daily_budget:
        return False
    return day_load_used(day_pois) / daily_budget < min_ratio


def balance_day_buckets(
    buckets: list[list[dict[str, Any]]],
    pool: list[dict[str, Any]],
    *,
    daily_budget: int,
    max_per_day: int,
    min_pois_per_day: int,
    min_day_load_ratio: float,
    min_supplement_style_affinity: float = 0.0,
    seed_names: set[str] | None = None,
) -> list[list[dict[str, Any]]]:
    """装箱后补齐「景点过少 / 负荷过低」的日期，避免中等体力只排一个 2 小时点。"""
    from backend.planning.visit_sites import cluster_key_for_poi

    if not pool or not buckets:
        return buckets

    seeds = seed_names or set()
    assigned_clusters: set[str] = set()
    for day in buckets:
        for poi in day:
            key = cluster_key_for_poi(poi, seeds)
            if key:
                assigned_clusters.add(key)

    unassigned: list[dict[str, Any]] = []
    for poi in pool:
        key = cluster_key_for_poi(poi, seeds)
        if key and key in assigned_clusters:
            continue
        unassigned.append(poi)

    for day_index, day_pois in enumerate(buckets):
        if not _day_needs_backfill(day_pois, daily_budget, min_pois_per_day, min_day_load_ratio):
            continue
        fill_candidates = sorted(
            unassigned,
            key=lambda p: (
                0 if p.get("preference_hit") else 1,
                -float(p.get("style_affinity", 0.0) or 0.0),
                int(p.get("activity_load", LOAD_STANDARD) or LOAD_STANDARD),
                -float(p.get("suitability_score", 0.0) or 0.0),
            ),
        )
        for poi in list(fill_candidates):
            cluster = cluster_key_for_poi(poi, seeds)
            if cluster and cluster in assigned_clusters:
                continue
            affinity = float(poi.get("style_affinity", 0.0) or 0.0)
            if not poi.get("preference_hit") and affinity < min_supplement_style_affinity:
                continue
            if not can_assign_poi_to_day(
                day_pois,
                poi,
                daily_budget,
                max_per_day,
                budget_margin=BACKFILL_BUDGET_MARGIN,
            ):
                continue
            day_pois.append(poi)
            unassigned.remove(poi)
            if cluster:
                assigned_clusters.add(cluster)
            if not _day_needs_backfill(day_pois, daily_budget, min_pois_per_day, min_day_load_ratio):
                break

    return buckets


def distribute_candidates_by_load(
    selected: list[dict[str, Any]],
    days: int,
    daily_budget: int,
    max_per_day: int,
    *,
    supplemental_pool: list[dict[str, Any]] | None = None,
    seed_names: set[str] | None = None,
    min_pois_per_day: int = 2,
    min_day_load_ratio: float = 0.5,
    min_supplement_style_affinity: float = 0.0,
) -> list[list[dict[str, Any]]]:
    """按活动负荷装箱分配：重景点优先占满独立日期，全程每景区簇仅出现一次。"""
    from backend.planning.visit_sites import cluster_key_for_poi

    buckets: list[list[dict[str, Any]]] = [[] for _ in range(days)]
    if not selected or days < 1:
        return buckets

    seeds = seed_names or set()
    used_clusters: set[str] = set()
    pool_max_load = max(int(p.get("activity_load", LOAD_STANDARD) or LOAD_STANDARD) for p in selected)
    if pool_max_load <= LOAD_HALF_DAY:
        # 城市日内多点：优先适配度，再按负荷升序装箱，避免「先塞一个 52 导致装不下 3 个 38」
        ordered = sorted(
            selected,
            key=lambda p: (
                -float(p.get("suitability_score", 0.0) or 0.0),
                int(p.get("activity_load", LOAD_STANDARD) or LOAD_STANDARD),
            ),
        )
    else:
        ordered = sorted(
            selected,
            key=lambda p: (
                -int(p.get("activity_load", LOAD_STANDARD) or LOAD_STANDARD),
                -float(p.get("suitability_score", 0.0) or 0.0),
            ),
        )

    for poi in ordered:
        cluster = cluster_key_for_poi(poi, seeds)
        if cluster and cluster in used_clusters:
            continue

        best_day = None
        best_key = None
        for day_index in range(days):
            if not can_assign_poi_to_day(buckets[day_index], poi, daily_budget, max_per_day):
                continue
            key = (day_load_used(buckets[day_index]), len(buckets[day_index]), day_index)
            if best_key is None or key < best_key:
                best_key = key
                best_day = day_index

        if best_day is None:
            continue
        buckets[best_day].append(poi)
        if cluster:
            used_clusters.add(cluster)

    return balance_day_buckets(
        buckets,
        supplemental_pool or ordered,
        daily_budget=daily_budget,
        max_per_day=max_per_day,
        min_pois_per_day=max(1, min_pois_per_day),
        min_day_load_ratio=min_day_load_ratio,
        min_supplement_style_affinity=min_supplement_style_affinity,
        seed_names=seeds,
    )


def summarize_day_activity(day_pois: list[dict[str, Any]], daily_budget: int) -> dict[str, Any]:
    used = day_load_used(day_pois)
    ratio = round(used / daily_budget, 2) if daily_budget else 0.0
    if ratio >= 0.92 or any(is_full_day_poi(p) for p in day_pois):
        intensity = "整日聚焦"
    elif ratio >= 0.72:
        intensity = "充实"
    elif ratio >= 0.45:
        intensity = "适中"
    else:
        intensity = "轻松"
    return {
        "activity_load_used": used,
        "activity_load_budget": daily_budget,
        "activity_load_ratio": ratio,
        "day_intensity": intensity,
    }


def build_day_note(day_pois: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    """补充说明：负荷数字由 itinerary 结构化字段展示，此处不重复。"""
    if not day_pois:
        return ""
    if any(is_full_day_poi(p) for p in day_pois):
        anchor = next(p for p in day_pois if is_full_day_poi(p))
        return (
            f"「{anchor['name']}」为整日级行程（约 {anchor.get('visit_hours', 6)} 小时），"
            f"当日不再叠加其它主力景点；请预留充足登山/游览与往返时间。"
        )
    if len(day_pois) == 1 and is_half_day_or_heavier(day_pois[0]):
        p = day_pois[0]
        return (
            f"以「{p['name']}」为主（{p.get('activity_tier_label', '半日')}，约 {p.get('visit_hours', 4)} 小时），"
            f"系统会优先按上午开场、午间补给与返程机动来编排；若同片区存在合适轻量点，会自动补入。"
        )
    site_notes = [
        str(p.get("visit_site_note", "")).strip()
        for p in day_pois
        if str(p.get("visit_site_note", "")).strip()
    ]
    if site_notes:
        return f"{'；'.join(site_notes[:2])}。具体时段见下方时间轴。"
    return "已按体力节奏排定顺序与时长，具体时段见下方时间轴，可按天气与排队微调。"


def _minutes_to_hhmm(total_minutes: int) -> str:
    total_minutes = max(0, min(total_minutes, 23 * 60 + 59))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def build_activity_timeline(day_pois: list[dict[str, Any]]) -> list[dict[str, str]]:
    from backend.planning.day_schedule import build_activity_timeline as _build

    return _build(day_pois)
