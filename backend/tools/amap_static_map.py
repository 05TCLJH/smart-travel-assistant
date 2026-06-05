"""高德静态地图预览支撑模块。

负责静态地图预览链接组装、标记点去重与标签文本清洗。
"""

from __future__ import annotations

from typing import Any
from backend.core.runtime_context import get_runtime_owner_id
from backend.core.settings import amap_key
from backend.runtime.state_store import runtime_state_store


class AmapStaticMapSupport:
    """静态地图预览支撑器。"""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    @staticmethod
    def estimate_static_map_zoom(points: list[tuple[float, float]]) -> int:
        """根据点位跨度估算缩放级别。"""
        if len(points) <= 1:
            return 14
        lngs = [point[0] for point in points]
        lats = [point[1] for point in points]
        span = max(max(lngs) - min(lngs), max(lats) - min(lats))
        if span > 8:
            return 5
        if span > 4:
            return 6
        if span > 2:
            return 7
        if span > 1:
            return 8
        if span > 0.6:
            return 9
        if span > 0.3:
            return 10
        if span > 0.15:
            return 11
        if span > 0.08:
            return 12
        if span > 0.04:
            return 13
        return 14

    def build_static_map_preview(self, route_geometry: dict[str, Any], day_pois: list[dict[str, Any]]) -> str:
        """生成静态地图预览链接。"""
        key = amap_key()
        owner_id = get_runtime_owner_id()
        if not key or not owner_id:
            return ""

        polyline_points = route_geometry.get("polyline", []) or []
        use_real_path = bool(route_geometry.get("draw_path")) or str(route_geometry.get("status", "")).strip() == "ok"
        marker_points: list[tuple[float, float]] = []
        for poi in day_pois:
            loc = str(poi.get("location", "")).strip()
            if not self._owner.parse_lnglat(loc):
                loc = self._owner._ensure_poi_location(poi, destination=str(poi.get("city", "")))
            point = self._owner.parse_lnglat(loc)
            if point:
                marker_points.append(point)

        dedup_points: list[tuple[float, float]] = []
        seen_xy: set[tuple[float, float]] = set()
        for point in marker_points:
            key_xy = (round(point[0], 4), round(point[1], 4))
            if key_xy in seen_xy:
                continue
            seen_xy.add(key_xy)
            dedup_points.append(point)
        marker_points = dedup_points
        if not polyline_points and not marker_points:
            return ""

        points_for_path = polyline_points if use_real_path else []
        path_segment = ";".join(
            f"{lng:.6f},{lat:.6f}"
            for lng, lat in points_for_path
            if lng is not None and lat is not None
        )

        markers: list[str] = []
        for index, point in enumerate(marker_points[:8], start=1):
            label = str(index) if index < 10 else "A"
            markers.append(f"mid,0xE45B5B,{label}:{point[0]:.6f},{point[1]:.6f}")

        marker_value = "|".join(markers) if markers else ""
        if path_segment:
            path_value = f"8,0x2F7CF6,0.85,,0:{path_segment}"
        else:
            path_value = ""
        payload = {
            "markers": marker_value,
            "paths": path_value,
            "size": "760*360",
        }
        ticket_id = runtime_state_store.create_static_map_ticket(owner_id, key, payload)
        return f"/api/trip/static-map?ticket={ticket_id}"

    @staticmethod
    def static_map_label_text(name: str) -> str:
        """清洗标签文本，避免分隔符影响静态地图渲染。"""
        text = str(name or "").strip().replace(",", " ").replace("|", " ").replace(":", " ")[:12]
        return text or "景点"
