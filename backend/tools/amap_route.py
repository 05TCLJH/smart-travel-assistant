"""高德路线解析模块。

负责路线接口返回的结构抽取、折线解码与路线适配器封装，让主工具类聚焦编排逻辑。
"""

from __future__ import annotations

from typing import Any

from backend.tools.amap_common import safe_int


class _AmapRouteAdapter:
    """把调研工具实例适配为路线规划器所需接口。"""

    def __init__(self, tools: Any) -> None:
        self._tools = tools

    def ensure_poi_location(self, poi: dict[str, Any], destination: str = "") -> str:
        return self._tools._ensure_poi_location(poi, destination=destination)

    def parse_lnglat(self, value: str) -> tuple[float, float] | None:
        return self._tools.parse_lnglat(value)

    def distance_km(self, a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
        return self._tools.distance_km(a, b)

    def parse_route_segment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tools._parse_route_segment(payload)


def order_lng_lat(first: float, second: float) -> tuple[float, float]:
    """把坐标纠正为经度在前、纬度在后的顺序。"""

    def is_mainland_lng(value: float) -> bool:
        return 70.0 <= value <= 140.0

    def is_mainland_lat(value: float) -> bool:
        return 15.0 <= value <= 55.0

    if is_mainland_lng(first) and is_mainland_lat(second):
        return first, second
    if is_mainland_lat(first) and is_mainland_lng(second):
        return second, first
    return first, second


def extract_direction_paths(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """从多层嵌套的高德路线结果中提取路径列表。"""
    if not isinstance(payload, dict):
        return []
    route = payload.get("route")
    if isinstance(route, dict):
        paths = route.get("paths")
        if isinstance(paths, list) and paths:
            return [item for item in paths if isinstance(item, dict)]
    paths = payload.get("paths")
    if isinstance(paths, list) and paths:
        return [item for item in paths if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        return extract_direction_paths(data)
    result = payload.get("result")
    if isinstance(result, dict):
        return extract_direction_paths(result)
    output = payload.get("output")
    if isinstance(output, dict):
        return extract_direction_paths(output)
    return []


def decode_polyline_string(
    raw: str,
    *,
    parse_lnglat_fn: Any,
    order_lng_lat_fn: Any = order_lng_lat,
) -> list[list[float]]:
    """把高德 polyline 字符串解码为坐标序列。"""
    text = str(raw or "").strip()
    if not text:
        return []
    if "|" in text and ";" not in text:
        parts = text.split("|")
    else:
        parts = text.split(";")
    points: list[list[float]] = []
    for chunk in parts:
        current = chunk.strip()
        if not current:
            continue
        if "," in current:
            point = parse_lnglat_fn(current)
            if point:
                points.append([point[0], point[1]])
        else:
            nums = current.replace(",", " ").split()
            if len(nums) >= 2:
                try:
                    first = float(nums[0])
                    second = float(nums[1])
                    lng, lat = order_lng_lat_fn(first, second)
                    points.append([lng, lat])
                except ValueError:
                    continue
    return points


def polyline_points_from_path(
    path: dict[str, Any],
    *,
    parse_lnglat_fn: Any,
    order_lng_lat_fn: Any = order_lng_lat,
) -> list[list[float]]:
    """优先使用 steps.polyline，其次回退到 path.polyline 与 tmcs.polyline。"""
    if not isinstance(path, dict):
        return []
    polyline: list[list[float]] = []
    steps = path.get("steps", []) or []
    for step in steps:
        if not isinstance(step, dict):
            continue
        seg_pl = step.get("polyline") or step.get("poly_line") or ""
        for point in decode_polyline_string(
            str(seg_pl),
            parse_lnglat_fn=parse_lnglat_fn,
            order_lng_lat_fn=order_lng_lat_fn,
        ):
            if not polyline or polyline[-1] != point:
                polyline.append(point)

    if not polyline:
        top = path.get("polyline") or path.get("poly_line") or ""
        polyline.extend(
            decode_polyline_string(
                str(top),
                parse_lnglat_fn=parse_lnglat_fn,
                order_lng_lat_fn=order_lng_lat_fn,
            )
        )

    if not polyline:
        tmcs = path.get("tmcs", []) or []
        if isinstance(tmcs, list):
            for item in tmcs:
                if not isinstance(item, dict):
                    continue
                seg_pl = item.get("polyline") or ""
                for point in decode_polyline_string(
                    str(seg_pl),
                    parse_lnglat_fn=parse_lnglat_fn,
                    order_lng_lat_fn=order_lng_lat_fn,
                ):
                    if not polyline or polyline[-1] != point:
                        polyline.append(point)

    return polyline


def parse_route_segment(payload: dict[str, Any], *, parse_lnglat_fn: Any) -> dict[str, Any]:
    """把高德路线返回转换为统一的距离、时长、折线和步骤结构。"""
    paths = extract_direction_paths(payload)
    first = paths[0] if paths else {}
    steps = first.get("steps", []) or [] if isinstance(first, dict) else []
    polyline = (
        polyline_points_from_path(first, parse_lnglat_fn=parse_lnglat_fn, order_lng_lat_fn=order_lng_lat)
        if isinstance(first, dict)
        else []
    )

    normalized_steps: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        instruction = str(step.get("instruction", "") or step.get("assistant_action", "")).strip()
        if instruction:
            normalized_steps.append({"instruction": instruction, "distance": safe_int(step.get("distance", 0), 0)})

    return {
        "distance_m": safe_int(first.get("distance", 0)) if isinstance(first, dict) else 0,
        "duration_s": safe_int(first.get("duration", 0)) if isinstance(first, dict) else 0,
        "polyline": polyline,
        "steps": normalized_steps,
    }
