"""单日路线规划：按交通方式调用高德路径服务，缺少道路轨迹时不画直线。"""

from __future__ import annotations

from typing import Any, Protocol

from backend.planning.route_geometry.types import DayRouteGeometry
from backend.tools.grounding_tools import normalize_admin_name


class RouteCoordinateResolver(Protocol):
    def ensure_poi_location(self, poi: dict[str, Any], destination: str = "") -> str: ...

    def parse_lnglat(self, value: str) -> tuple[float, float] | None: ...

    def distance_km(self, a: tuple[float, float] | None, b: tuple[float, float] | None) -> float: ...

    def parse_route_segment(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class RouteApiClient(Protocol):
    @property
    def enabled(self) -> bool: ...

    def driving_route(self, origin: str, destination: str, waypoints: list[str] | None = None) -> dict[str, Any]: ...

    def walking_route(self, origin: str, destination: str) -> dict[str, Any]: ...

    def transit_route(self, origin: str, destination: str, city: str, cityd: str = "") -> dict[str, Any]: ...


MODE_LABELS = {
    "driving": "驾车",
    "walking": "步行",
    "transit": "公共交通",
}


def resolve_effective_mode(
    route_profile: str,
    coords: list[str],
    *,
    distance_km_fn,
    parse_lnglat_fn,
) -> str:
    """结合用户策略与段距，决定实际调用的高德路径 API。"""
    profile = str(route_profile or "driving").strip().lower()
    pairs = [parse_lnglat_fn(c) for c in coords]
    pairs = [p for p in pairs if p]
    max_seg_km = 0.0
    for left, right in zip(pairs, pairs[1:]):
        max_seg_km = max(max_seg_km, float(distance_km_fn(left, right) or 0.0))

    if profile == "transit":
        return "transit"
    if profile == "walking":
        return "walking" if max_seg_km <= 5.0 else "driving"
    if profile == "mixed":
        return "walking" if max_seg_km <= 2.5 else "driving"
    return "driving"


def _haversine_plan(coords: list[str], *, parse_lnglat_fn, distance_km_fn, reason: str) -> DayRouteGeometry:
    pairs = [parse_lnglat_fn(c) for c in coords]
    pairs = [p for p in pairs if p]
    total_km = 0.0
    for left, right in zip(pairs, pairs[1:]):
        total_km += float(distance_km_fn(left, right) or 0.0)
    distance_m = int(total_km * 1000)
    duration_s = int(total_km / 35 * 3600) if total_km > 0 else 0
    return DayRouteGeometry(
        status="metrics_only",
        provider="fallback-estimator",
        route_profile="driving",
        effective_mode="driving",
        distance_m=distance_m,
        duration_s=duration_s,
        polyline=[],
        steps=[],
        draw_path=False,
        message=reason,
    )


def _city_for_transit(day_pois: list[dict[str, Any]], dest_hint: str) -> str:
    for poi in day_pois:
        for key in ("city", "district"):
            text = normalize_admin_name(str(poi.get(key, "")).strip())
            if text and len(text) >= 2:
                return text
    return normalize_admin_name(dest_hint) or dest_hint


def _mode_summary(mode: str, distance_m: int, duration_s: int) -> str:
    label = MODE_LABELS.get(mode, "出行")
    dist = f"{distance_m / 1000:.1f} 公里" if distance_m >= 1000 else f"{distance_m} 米"
    mins = max(1, round(duration_s / 60)) if duration_s >= 60 else 0
    time_part = f"，预计 {label} {mins} 分钟" if mins else ""
    return f"高德估算全程约 {dist}{time_part}"


class DayRoutePlanner:
    """编排单日动线：优先单次多途经点驾车规划，减少 QPS 并获取完整道路 polyline。"""

    def __init__(self, coords: RouteCoordinateResolver, amap: RouteApiClient) -> None:
        self._coords = coords
        self._amap = amap

    def plan(
        self,
        day_pois: list[dict[str, Any]],
        *,
        route_profile: str = "driving",
        destination_hint: str = "",
    ) -> DayRouteGeometry:
        dest_hint = str(destination_hint or (day_pois[0] or {}).get("city", "")).strip() if day_pois else ""
        coord_texts = [self._coords.ensure_poi_location(poi, destination=dest_hint) for poi in day_pois]
        coord_texts = [c for c in coord_texts if c]
        profile = str(route_profile or "driving").strip().lower()

        if len(coord_texts) < 2:
            return DayRouteGeometry(
                status="no_waypoints",
                provider="none",
                route_profile=profile,
                effective_mode=profile,
                message="当日仅 1 个景点，无需串联路线。",
            )

        effective = resolve_effective_mode(
            profile,
            coord_texts,
            distance_km_fn=self._coords.distance_km,
            parse_lnglat_fn=self._coords.parse_lnglat,
        )

        if not self._amap.enabled:
            return _haversine_plan(
                coord_texts,
                parse_lnglat_fn=self._coords.parse_lnglat,
                distance_km_fn=self._coords.distance_km,
                reason="未配置高德路径服务，仅提供直线距离估算，地图不绘制连线。",
            )

        try:
            payload = self._fetch_route_payload(coord_texts, effective, day_pois, dest_hint)
            segment = self._coords.parse_route_segment(payload)
            polyline = list(segment.get("polyline") or [])
            distance_m = int(segment.get("distance_m") or 0)
            duration_s = int(segment.get("duration_s") or 0)
            steps = list(segment.get("steps") or [])

            if distance_m <= 0 and polyline:
                distance_m = self._estimate_polyline_distance_m(polyline)

            # 高德在部分线段上可能只给到 2 个折点（起终），仍可沿道路绘制简单路径，优于完全无连线。
            has_road_polyline = len(polyline) >= 2
            if has_road_polyline:
                return DayRouteGeometry(
                    status="ok",
                    provider="amap-mcp",
                    route_profile=profile,
                    effective_mode=effective,
                    distance_m=distance_m,
                    duration_s=duration_s,
                    polyline=polyline,
                    steps=steps,
                    draw_path=True,
                    message=_mode_summary(effective, distance_m, duration_s),
                )

            if distance_m > 0 or duration_s > 0:
                return DayRouteGeometry(
                    status="metrics_only",
                    provider="amap-mcp",
                    route_profile=profile,
                    effective_mode=effective,
                    distance_m=distance_m,
                    duration_s=duration_s,
                    polyline=[],
                    steps=steps,
                    draw_path=False,
                    message=_mode_summary(effective, distance_m, duration_s),
                )

            return _haversine_plan(
                coord_texts,
                parse_lnglat_fn=self._coords.parse_lnglat,
                distance_km_fn=self._coords.distance_km,
                reason="未能获取高德路径结果，地图仅标注景点。",
            )
        except Exception as exc:
            fallback = _haversine_plan(
                coord_texts,
                parse_lnglat_fn=self._coords.parse_lnglat,
                distance_km_fn=self._coords.distance_km,
                reason="",
            )
            fallback.status = "failed"
            fallback.provider = "amap-mcp"
            fallback.route_profile = profile
            fallback.effective_mode = effective
            fallback.message = f"路径规划暂不可用（{exc}），地图仅标注景点顺序。"
            return fallback

    def _fetch_route_payload(
        self,
        coords: list[str],
        effective_mode: str,
        day_pois: list[dict[str, Any]],
        dest_hint: str,
    ) -> dict[str, Any]:
        origin, destination = coords[0], coords[-1]
        if effective_mode == "walking":
            if len(coords) == 2:
                return self._amap.walking_route(origin, destination)
            merged: dict[str, Any] = {"route": {"paths": [{"distance": 0, "duration": 0, "steps": []}]}}
            path = merged["route"]["paths"][0]
            for left, right in zip(coords, coords[1:]):
                seg_payload = self._amap.walking_route(left, right)
                seg = self._coords.parse_route_segment(seg_payload)
                path["distance"] = int(path.get("distance", 0)) + int(seg.get("distance_m", 0))
                path["duration"] = int(path.get("duration", 0)) + int(seg.get("duration_s", 0))
                path["steps"].extend(seg.get("steps") or [])
                if seg.get("polyline"):
                    top = path.setdefault("polyline", "")
                    extra = ";".join(f"{p[0]:.6f},{p[1]:.6f}" for p in seg["polyline"])
                    path["polyline"] = f"{top};{extra}".strip(";") if top else extra
            return merged

        if effective_mode == "transit":
            city = _city_for_transit(day_pois, dest_hint)
            if len(coords) == 2:
                return self._amap.transit_route(origin, destination, city=city)
            # 公交暂不支持多途经点：取首段公交 + 其余驾车（减少直线）
            first = self._amap.transit_route(coords[0], coords[1], city=city)
            if len(coords) == 2:
                return first
            tail = self._amap.driving_route(coords[1], destination, waypoints=coords[2:-1] or None)
            return self._merge_segment_payloads([first, tail])

        waypoints = coords[1:-1] if len(coords) > 2 else None
        return self._amap.driving_route(origin, destination, waypoints=waypoints)

    @staticmethod
    def _merge_segment_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
        merged_path: dict[str, Any] = {"distance": 0, "duration": 0, "steps": [], "polyline": ""}
        for payload in payloads:
            paths = payload.get("route", {}).get("paths") if isinstance(payload.get("route"), dict) else payload.get("paths")
            if not isinstance(paths, list) or not paths:
                continue
            first = paths[0]
            if not isinstance(first, dict):
                continue
            merged_path["distance"] = int(merged_path.get("distance", 0)) + int(first.get("distance", 0) or 0)
            merged_path["duration"] = int(merged_path.get("duration", 0)) + int(first.get("duration", 0) or 0)
            merged_path["steps"].extend(first.get("steps") or [])
            pl = str(first.get("polyline") or "").strip()
            if pl:
                existing = str(merged_path.get("polyline") or "").strip()
                merged_path["polyline"] = f"{existing};{pl}".strip(";") if existing else pl
        return {"route": {"paths": [merged_path]}}

    @staticmethod
    def _estimate_polyline_distance_m(polyline: list[list[float]]) -> int:
        if len(polyline) < 2:
            return 0
        from backend.planning.poi_retrieval.geo import distance_km

        total_km = 0.0
        for left, right in zip(polyline, polyline[1:]):
            total_km += distance_km(tuple(left), tuple(right))
        return int(total_km * 1000)
