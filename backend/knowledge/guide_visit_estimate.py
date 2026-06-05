"""导游视角：由景点种子名估算典型游览时长与排期档位。

用于 bootstrap 写入 visit_profiles，以及规则引擎兜底。
原则：先定真实停留小时（导游经验），再映射 activity_tier / activity_load。
"""

from __future__ import annotations

import re
from typing import Any

from backend.planning.visit_duration import (
    TIER_LOAD,
    compose_visit_metrics,
    infer_schedule_mode,
)

# ---------- 1. 过路打卡（约 1 小时）----------
_LIGHT_MARKERS = (
    "大桥",
    "立交桥",
    "音乐喷泉",
    "喷泉广场",
    "摩天轮",
    "观景台",
    "观景平台",
    "观景塔",
    "牌楼",
    "牌坊",
    "门楼",
    "驿站",
    "索道站",
    "缆车站",
    "游客中心",
    "售票处",
)

# ---------- 2. 整日户外（约 6.5 至 8 小时）----------
_FULL_DAY_MARKERS = (
    "国家森林公园",
    "国家地质公园",
    "国家级风景名胜区",
    "世界遗产",
    "自然保护区",
    "风景名胜区",
    "风景旅游区",
    "旅游风景区",
    "大峡谷",
    "大草原",
    "空中草原",
    "高原草原",
    "沙漠公园",
    "雪山景区",
    "冰川",
    "国家公园",
    "森林公园",
    "黄山",
    "华山",
    "峨眉山",
    "武功山",
    "九寨沟",
    "张家界",
    "长白山",
    "天池",
    "喀纳斯",
)

# ---------- 3. 半日户外 / 大景区（约 4 至 6 小时）----------
_HALF_DAY_OUTDOOR_MARKERS = (
    "草原",
    "湖泊",
    "湿地公园",
    "古城",
    "古镇",
    "古村",
    "古街",
    "历史街区",
    "民俗文化村",
    "民俗村",
    "风情小镇",
    "旅游度假区",
    "度假区",
    "主题乐园",
    "迪士尼",
    "环球影城",
    "欢乐谷",
    "方特",
    "长隆",
    "动物园",
    "野生动物园",
    "博览园",
    "博览区",
    "园博园",
    "遗址公园",
    "古道",
    "大峡谷",
    "溶洞",
    "瀑布",
    "雪山",
    "湿地",
)

# 名称含湖海但非大桥/喷泉
_LAKE_SEA_RE = re.compile(r"(湖|海|泊|潭|水库)(?!大桥|喷泉)")

# ---------- 4. 馆内单次入馆（连续入馆模式）----------
_NATIONAL_MUSEUM_MARKERS = ("国家博物馆", "中国博物馆", "故宫博物院", "故宫")
_PROVINCIAL_MUSEUM_MARKERS = ("省博物馆", "市博物馆", "自治区博物馆")
_MUSEUM_MARKERS = ("博物馆", "博物院")
_MEMORIAL_MARKERS = ("纪念馆", "纪念园", "纪念堂", "陈列馆", "陈列大楼", "展览馆")
_TEMPLE_MARKERS = ("寺", "庙", "祠", "庵", "观")
_RESIDENCE_MARKERS = ("故居", "旧居", "府", "书院")

# ---------- 5. 城市漫步 / 街区（约 2 至 3 小时）----------
_STREET_MARKERS = ("步行街", "老街", "巷子", "里弄", "历史文化街", "风情街", "夜市", "坊", "里", "文旅", "水镇", "老街")

# 其它常见旅游形态
_WETLAND_PARK_MARKERS = ("湿地公园", "湿地", "海滨", "海滩", "沙滩")
_THEME_MARKERS = ("欢乐谷", "方特", "长隆", "海洋世界", "海底世界", "水族馆", "蜡像馆", "影视城", "科幻城")
_SPRING_SKI_MARKERS = ("温泉", "滑雪场", "滑雪", "漂流", "滑道")
_CULTURAL_BLOCK_MARKERS = ("历史文化", "风情街", "文创", "民俗", "非遗", "坊巷")


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in text for m in markers)


def _is_light_landmark(name: str) -> bool:
    if _has_any(name, _LIGHT_MARKERS):
        return True
    if "广场" in name and "喷泉" not in name and len(name) <= 12:
        return True
    return False


def _is_museum_or_memorial(name: str) -> bool:
    return _has_any(
        name,
        _MUSEUM_MARKERS + _MEMORIAL_MARKERS + _NATIONAL_MUSEUM_MARKERS + _PROVINCIAL_MUSEUM_MARKERS,
    ) or "博物" in name


def _is_full_day_scenic(name: str) -> bool:
    if _is_museum_or_memorial(name):
        return False
    if _has_any(name, _FULL_DAY_MARKERS):
        return True
    if "世界遗产" in name and _has_any(name, ("景区", "风景区", "风景名胜", "公园", "大峡谷")):
        return True
    if _LAKE_SEA_RE.search(name) and _has_any(name, ("风景名胜区", "国家森林公园", "风景区")):
        return True
    if "山" in name and _has_any(name, ("景区", "风景区", "风景名胜", "国家公园", "森林公园")):
        return True
    return False


def _is_half_day_outdoor(name: str) -> bool:
    if _has_any(name, _HALF_DAY_OUTDOOR_MARKERS):
        return True
    if _LAKE_SEA_RE.search(name):
        return True
    return False


# 知名景点显式校准（与内置景点画像数据文件同步维护）
_BUILTIN_SEEDS: dict[str, tuple[str, float]] = {
    "西湖": ("half_day", 4.0),
    "西湖风景名胜区": ("half_day", 4.0),
    "东湖": ("half_day", 4.0),
    "东湖生态旅游风景区": ("half_day", 4.0),
    "洱海": ("half_day", 5.0),
    "洱海生态廊道": ("extended", 3.0),
    "滇池": ("half_day", 4.5),
    "千岛湖": ("half_day", 5.0),
    "泸沽湖": ("half_day", 5.5),
    "天门山": ("half_day", 5.0),
    "天门山国家森林公园": ("full_day", 7.0),
    "张家界国家森林公园": ("full_day", 7.5),
    "张家界博物院": ("extended", 2.5),
    "武夷山": ("half_day", 5.0),
}


def estimate_guide_visit(name: str, *, region_type: str = "city") -> dict[str, Any]:
    """返回 typical_visit_hours、activity_tier 等（已规范化）。"""
    from backend.planning.venue_visit_resolver import resolve_poi_visit_metrics

    text = str(name or "").strip()
    if text in _BUILTIN_SEEDS:
        tier, hours = _BUILTIN_SEEDS[text]
        poi = {"name": text, "type": ""}
        mode = infer_schedule_mode(poi)
        load = TIER_LOAD.get(tier, 38)
        composed = compose_visit_metrics(
            activity_load=load,
            activity_tier=tier,
            poi=poi,
            typical_visit_hours=hours,
            schedule_mode=mode,
        )
        return {**composed, "activity_load_source": "guide_seed"}

    resolved = resolve_poi_visit_metrics({"name": text}, region_type=region_type)
    payload = dict(resolved)
    if payload.get("venue_archetype") != "generic_standard":
        payload["activity_load_source"] = "guide"
    return payload


def guide_classified(metrics: dict[str, Any]) -> bool:
    """是否命中了具体导游规则（而非末尾 2h 兜底）。"""
    if metrics.get("venue_archetype") and metrics.get("venue_archetype") != "generic_standard":
        return True
    if metrics.get("activity_load_source") in {"guide", "guide_seed", "archetype"}:
        return True
    tier = str(metrics.get("activity_tier", "")).strip()
    hours = float(metrics.get("visit_hours", 0) or 0)
    if tier != "standard":
        return True
    if abs(hours - 2.0) > 0.15:
        return True
    if str(metrics.get("schedule_mode", "")) == "contiguous_gate":
        return True
    return False


def guide_profile_for_knowledge(name: str, *, region_type: str = "city") -> dict[str, Any]:
    """写入 destination_knowledge.json 的 slim 字段。"""
    m = estimate_guide_visit(name, region_type=region_type)
    return {
        "typical_visit_hours": m["visit_hours"],
        "activity_tier": m["activity_tier"],
    }
