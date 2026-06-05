"""地理坐标解析与距离计算，供景点检索层专用。"""

from __future__ import annotations

import math


def order_lng_lat(first: float, second: float) -> tuple[float, float]:
    """高德坐标为「经度,纬度」；部分数据源会写成「纬度,经度」，在中国大陆范围内做简单纠正。"""

    def is_mainland_lng(x: float) -> bool:
        return 70.0 <= x <= 140.0

    def is_mainland_lat(x: float) -> bool:
        return 15.0 <= x <= 55.0

    if is_mainland_lng(first) and is_mainland_lat(second):
        return first, second
    if is_mainland_lat(first) and is_mainland_lng(second):
        return second, first
    return first, second


def parse_lnglat(value: str) -> tuple[float, float] | None:
    raw = str(value or "").strip()
    if "," not in raw:
        return None
    try:
        a, b = raw.split(",", 1)
        first, second = float(a.strip()), float(b.strip())
        return order_lng_lat(first, second)
    except ValueError:
        return None


def distance_km(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
    if not a or not b:
        return 0.0
    lng1, lat1 = a
    lng2, lat2 = b
    return math.sqrt((lng1 - lng2) ** 2 + (lat1 - lat2) ** 2) * 111
