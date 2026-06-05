"""游览时长与排期负荷：两套语义分离。

- activity_load：日程装箱用的抽象体力单位（100 ≈ 一日容量），用于 can_assign / 分日。
- visit_hours：导游视角的馆内/景区内停留时长，仅用于时间轴与文案。
- schedule_mode：时间轴编排策略（是否允许午餐打断单次入馆）。
"""

from __future__ import annotations

import re
from typing import Any, Literal

ScheduleMode = Literal["contiguous_gate", "flexible", "full_day_outdoor", "theme_park"]

# 各排期模式与体力档位对应最短和最长小时数；主题乐园模式由场馆形态注册表驱动
TIER_HOURS_RANGE: dict[ScheduleMode, dict[str, tuple[float, float]]] = {
    "contiguous_gate": {
        "light": (0.8, 1.5),
        "standard": (1.5, 2.5),
        "extended": (2.0, 3.0),
        "half_day": (2.5, 3.5),
        "full_day": (4.0, 5.5),
    },
    "flexible": {
        "light": (1.0, 2.0),
        "standard": (1.5, 3.0),
        "extended": (2.0, 3.5),
        "half_day": (3.0, 5.0),
        "full_day": (5.0, 7.0),
    },
    "full_day_outdoor": {
        "light": (2.0, 3.5),
        "standard": (3.0, 5.0),
        "extended": (4.0, 6.0),
        "half_day": (5.0, 6.5),
        "full_day": (6.5, 9.0),
    },
    "theme_park": {
        "light": (4.0, 5.0),
        "standard": (5.0, 6.0),
        "extended": (5.5, 6.0),
        "half_day": (5.5, 6.5),
        "full_day": (6.0, 7.0),
    },
}

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

TIER_LOAD = {
    "light": LOAD_LIGHT,
    "standard": LOAD_STANDARD,
    "extended": LOAD_EXTENDED,
    "half_day": LOAD_HALF_DAY,
    "full_day": LOAD_FULL_DAY,
}

_CONTIGUOUS_MARKERS = (
    "博物馆",
    "博物院",
    "纪念馆",
    "纪念园",
    "纪念堂",
    "陈列馆",
    "陈列大楼",
    "展览馆",
    "美术馆",
    "艺术馆",
    "科技馆",
    "图书馆",
    "故居",
    "旧居",
    "陵",
    "墓",
    "遗址博物馆",
    "遗址公园",
)

_FULL_DAY_OUTDOOR_MARKERS = (
    "国家森林公园",
    "风景名胜区",
    "风景区",
    "大峡谷",
    "大草原",
    "雪山",
    "国家公园",
    "森林公园",
    "沙漠",
    "冰川",
    "草原",
    "湖泊",
    "湿地",
    "古道",
    "沙漠",
    "峡谷",
    "瀑布",
    "溶洞",
    "天池",
    "海子",
)


def infer_schedule_mode(poi: dict[str, Any]) -> ScheduleMode:
    """仅用于 generic_standard 等未命中 archetype 的兜底 POI。"""
    name = str(poi.get("name", "")).strip()
    type_text = str(poi.get("type", "")).strip()
    blob = f"{name} {type_text}"
    if any(m in blob for m in _CONTIGUOUS_MARKERS):
        return "contiguous_gate"
    if any(m in blob for m in _FULL_DAY_OUTDOOR_MARKERS):
        return "full_day_outdoor"
    if "寺" in name or "庙" in name or "祠" in name:
        return "contiguous_gate"
    if re.search(r"(湖|海|泊|潭|水库|草原|湿地)", name) and not any(
        x in name for x in ("大桥", "喷泉", "广场")
    ):
        return "full_day_outdoor"
    if "山" in name and any(x in name for x in ("景区", "风景区", "风景名胜")):
        return "full_day_outdoor"
    if "山" in name and "公园" in name:
        return "flexible"
    return "flexible"


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


def hours_to_load(hours: float, tier: str | None = None) -> int:
    tier_norm = str(tier or "").strip().lower()
    if tier_norm in TIER_LOAD:
        return TIER_LOAD[tier_norm]
    try:
        h = float(hours)
    except (TypeError, ValueError):
        h = 2.0
    return max(LOAD_LIGHT, min(LOAD_FULL_DAY, int(round(h / 8.5 * 100))))


def clamp_visit_hours(
    hours: float | None,
    tier: str,
    mode: ScheduleMode,
) -> float:
    """将时长限制在导游合理的档位区间内（修正 bootstrap 用负荷反推的 6h+ 博物馆）。"""
    tier = tier if tier in TIER_LOAD else "standard"
    lo, hi = TIER_HOURS_RANGE.get(mode, TIER_HOURS_RANGE["flexible"]).get(tier, (1.5, 2.5))
    if hours is None:
        return round((lo + hi) / 2, 1)
    try:
        value = float(hours)
    except (TypeError, ValueError):
        value = (lo + hi) / 2
    return round(max(lo, min(value, hi)), 1)


def compose_visit_metrics(
    *,
    activity_load: int,
    activity_tier: str,
    poi: dict[str, Any] | None = None,
    typical_visit_hours: float | None = None,
    schedule_mode: ScheduleMode | None = None,
) -> dict[str, Any]:
    """由排期档位 + 可选知识库时长，生成一致的 load / hours / mode。"""
    tier = str(activity_tier or _load_to_tier(activity_load)).strip().lower()
    if tier not in TIER_LOAD:
        tier = _load_to_tier(activity_load)
    mode = schedule_mode or (infer_schedule_mode(poi) if poi else "flexible")
    hours = clamp_visit_hours(typical_visit_hours, tier, mode)
    load = TIER_LOAD.get(tier, hours_to_load(hours, tier))
    return {
        "activity_load": load,
        "visit_hours": hours,
        "activity_tier": tier,
        "activity_tier_label": TIER_LABELS.get(tier, "常规"),
        "schedule_mode": mode,
    }


def metrics_from_rules_payload(rules: dict[str, Any], poi: dict[str, Any]) -> dict[str, Any]:
    """规则引擎只产出档位与负荷；真实时长由本模块派生。"""
    merged = compose_visit_metrics(
        activity_load=int(rules.get("activity_load", LOAD_STANDARD) or LOAD_STANDARD),
        activity_tier=str(rules.get("activity_tier", "standard")),
        poi=poi,
        typical_visit_hours=None,
    )
    return {
        **merged,
        "activity_load_source": rules.get("activity_load_source", "rules"),
    }
