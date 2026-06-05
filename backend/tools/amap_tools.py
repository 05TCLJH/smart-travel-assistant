"""基于高德官方服务的数据采集与地图天气工具。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from collections.abc import Callable
import threading
from typing import Any

from backend.core.settings import amap_key, env_bool, env_float, first_env
from backend.planning.poi_retrieval import PoiRetrievalPipeline
from backend.planning.poi_retrieval.classifiers import (
    dedupe_name_key,
    guess_tags as infer_poi_tags,
    is_complex_sub_poi,
)
from backend.planning.poi_retrieval.geo import distance_km as geo_distance_km
from backend.planning.poi_retrieval.geo import parse_lnglat as geo_parse_lnglat
from backend.planning.search_strategy import (
    SearchStrategy,
    build_search_strategy,
)
from backend.mcp.amap_client import AmapMcpClient
from backend.tools.amap_common import safe_float, safe_int
from backend.tools.amap_geocode import (
    extract_destination_scope,
    extract_geocode_admin1,
    extract_geocode_location,
    extract_geocode_name,
)
from backend.tools.amap_route import (
    _AmapRouteAdapter,
    decode_polyline_string,
    extract_direction_paths,
    order_lng_lat,
    parse_route_segment,
    polyline_points_from_path,
)
from backend.tools.amap_poi_coordinates import AmapPoiCoordinateSupport, _PoiCoordinateCandidate
from backend.tools.amap_map_data import AmapMapDataSupport
from backend.tools.amap_poi_research import AmapPoiResearchSupport
from backend.tools.amap_static_map import AmapStaticMapSupport
from backend.tools.amap_weather import (
    extract_forecast_reporttime,
    fallback_weather_payload,
    format_weather_failure_reason,
    normalize_weather_payload,
    weather_rain_prob,
)


class TravelResearchTools:
    """供各 Agent 调用的调研侧工具集。"""

    DESTINATION_RADIUS_LIMIT_KM: dict[str, float] = {
        "北京": 90.0,
        "上海": 70.0,
        "重庆": 90.0,
        "天津": 70.0,
        "成都": 80.0,
    }

    def __init__(self) -> None:
        self.amap = AmapMcpClient()
        self._mcp_enabled_configured = env_bool("AMAP_MCP_ENABLED", True)
        self._mcp_enabled_override: bool | None = None
        self.osm_geocode_enabled = env_bool("OSM_GEOCODE_ENABLED", True)
        self._regeocode_cache: dict[str, dict[str, Any]] = {}
        self._osm_cache: dict[str, str] = {}
        self._map_data_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._geocode_payload_cache: dict[str, dict[str, Any]] = {}
        self._destination_scope_cache: dict[str, dict[str, Any]] = {}
        self._poi_coordinate_cache: dict[str, str] = {}
        self._poi_geocode_query_cache: dict[str, list[tuple[str, str]]] = {}
        self._poi_homonym_search_cache: dict[str, list[_PoiCoordinateCandidate]] = {}
        self._cache_lock = threading.Lock()
        self._poi_coordinate_support = AmapPoiCoordinateSupport(self)
        self._map_data_support = AmapMapDataSupport(self)
        self._poi_research_support = AmapPoiResearchSupport(self)
        self._static_map_support = AmapStaticMapSupport(self)
        self._poi_pipeline = PoiRetrievalPipeline(self)

    def reset_amap_connection(self) -> None:
        """关闭 MCP HTTP 会话并清空地理缓存，使新的 AMAP_* 环境变量立即生效。"""
        try:
            self.amap.close()
        except Exception:
            pass
        self._regeocode_cache.clear()
        self._osm_cache.clear()
        self._map_data_cache.clear()
        self._geocode_payload_cache.clear()
        self._destination_scope_cache.clear()
        self._poi_coordinate_cache.clear()
        self._poi_geocode_query_cache.clear()
        self._poi_homonym_search_cache.clear()

    def resolve_geocode_payload(self, query: str) -> dict[str, Any]:
        """缓存高德地理编码结果，供多个板块共享（线程安全）。"""
        text = str(query or "").strip()
        if not text or not (self.mcp_enabled and self.amap.enabled):
            return {}
        cache_key = f"{self.amap.server_url}|{text}"
        # 使用锁保护缓存检查 + 写入，避免并行执行时重复调用
        with self._cache_lock:
            cached = self._geocode_payload_cache.get(cache_key)
            if cached is not None:
                return deepcopy(cached)
            try:
                payload = self.amap.geocode(text)
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                self._geocode_payload_cache[cache_key] = deepcopy(payload)
                return deepcopy(payload)
            self._geocode_payload_cache[cache_key] = {}
        return {}

    def get_destination_scope(self, destination: str) -> dict[str, Any]:
        """缓存目的地作用域解析结果，避免同一请求多次地理编码。"""
        text = str(destination or "").strip()
        scope: dict[str, Any] = {
            "destination": text,
            "resolved_name": text,
            "city_ref": text,
            "anchor": None,
        }
        if not text:
            return scope

        cache_key = f"{self.amap.server_url}|{text}"
        cached = self._destination_scope_cache.get(cache_key)
        if cached is not None:
            return deepcopy(cached)

        if not self.amap.enabled:
            self._destination_scope_cache[cache_key] = deepcopy(scope)
            return deepcopy(scope)

        payload = self.resolve_geocode_payload(text)
        if payload:
            resolved_scope = extract_destination_scope(payload, text)
            location = self._extract_geocode_location(payload)
            scope.update(resolved_scope)
            scope["anchor"] = self.parse_lnglat(location)
            scope["city_ref"] = (
                str(resolved_scope.get("adcode", "")).strip()
                or str(resolved_scope.get("city", "")).strip()
                or text
            )

        self._destination_scope_cache[cache_key] = deepcopy(scope)
        return deepcopy(scope)

    @property
    def mcp_enabled(self) -> bool:
        """是否允许走高德实时链路。

        兼容两种场景：
        - 平台级显式启用 AMAP_MCP_ENABLED
        - 当前请求链路临时注入了可用的高德 Key
        """
        if self._mcp_enabled_override is not None:
            return self._mcp_enabled_override
        return self._mcp_enabled_configured or bool(first_env("AMAP_MCP_SERVER_URL") or amap_key())

    @mcp_enabled.setter
    def mcp_enabled(self, value: bool) -> None:
        self._mcp_enabled_override = bool(value)

    @staticmethod
    def build_dates(start_date: str, days: int) -> list[str]:
        start = date.fromisoformat(start_date)
        return [(start + timedelta(days=index)).isoformat() for index in range(days)]

    @staticmethod
    def normalize_request(trip_request: dict[str, Any]) -> dict[str, Any]:
        destination = str(trip_request.get("destination", "南昌")).strip() or "南昌"
        start_date = str(trip_request.get("start_date", (date.today() + timedelta(days=3)).isoformat()))
        days = max(1, min(safe_int(trip_request.get("days", 3), 3), 10))
        budget = max(0.0, safe_float(trip_request.get("budget", 3000), 3000.0))
        return {"destination": destination, "start_date": start_date, "days": days, "budget": budget}

    def build_weather(self, destination: str, dates: list[str]) -> dict[str, Any]:
        if not (self.mcp_enabled and self.amap.enabled):
            return self._fallback_weather(
                destination,
                dates,
                format_weather_failure_reason("当前会话未注入可用高德 Key，天气回退到本地估算。"),
            )

        resolved_name = destination
        geo: dict[str, Any] = {}
        weather_targets: list[str] = []
        try:
            geo_payload = self.resolve_geocode_payload(resolve_geocode_query(destination))
            resolved_name = self._extract_geocode_name(geo_payload, destination)
            location = self._extract_geocode_location(geo_payload)
            if location:
                lng, lat = location.split(",") if "," in location else ("0", "0")
                geo = {
                    "lng": safe_float(lng, 0.0),
                    "lat": safe_float(lat, 0.0),
                }
            for candidate in (
                self._extract_geocode_adcode(geo_payload),
                self._extract_destination_scope(geo_payload, destination).get("city", ""),
                resolved_name,
                destination,
            ):
                value = str(candidate or "").strip()
                if value and value not in weather_targets:
                    weather_targets.append(value)
        except Exception:
            weather_targets.append(destination)

        weather_payload: dict[str, Any] | None = None
        last_error = ""
        for target in weather_targets or [destination]:
            try:
                weather_payload = self.amap.weather(target, "all")
                break
            except Exception as exc:
                last_error = str(exc)

        if weather_payload is None:
            return self._fallback_weather(
                destination,
                dates,
                format_weather_failure_reason(last_error or "高德 MCP 天气服务不可用"),
            )

        daily_rows = self._normalize_weather_payload(destination, dates, weather_payload)
        if not daily_rows:
            return self._fallback_weather(
                destination,
                dates,
                format_weather_failure_reason(last_error or "高德 MCP 天气返回为空"),
            )
        scored = [row for row in daily_rows if not row.get("is_pending")]
        avg_rain = sum((row.get("rain_prob") or 0.0) for row in scored) / len(scored) if scored else 0.4
        rating = "优秀" if avg_rain < 0.25 else "良好" if avg_rain < 0.45 else "一般" if avg_rain < 0.65 else "较差"
        advice = {
            "优秀": "天气条件优秀，适合安排较多户外活动。",
            "良好": "整体适合出行，建议准备轻便雨具并关注临近预报。",
            "一般": "天气存在波动，建议室内外行程搭配安排。",
            "较差": "天气不稳定，建议优先考虑室内景点。",
        }[rating]
        live_rows = weather_payload.get("lives", []) if isinstance(weather_payload, dict) else []
        live_payload = live_rows[0] if live_rows and isinstance(live_rows[0], dict) else {}
        return {
            "destination": destination,
            "resolved_name": str(live_payload.get("city", "")).strip() or resolved_name,
            "geo": geo,
            "rating": rating,
            "live": {
                "city": live_payload.get("city", ""),
                "weather": live_payload.get("weather", ""),
                "temperature": live_payload.get("temperature", ""),
                "humidity": live_payload.get("humidity", ""),
                "reporttime": live_payload.get("reporttime", ""),
            },
            "daily": daily_rows,
            "advice": advice,
            "provider": "amap-mcp",
            "is_fallback": False,
            "forecast_reporttime": self._extract_forecast_reporttime(weather_payload),
        }

    def build_map_data(
        self,
        destination: str,
        persona: dict[str, Any],
        query_hint: str = "",
        *,
        emit_step: Callable[[str, str, str | None], None] | None = None,
    ) -> dict[str, Any]:
        return self._map_data_support.build_map_data(
            destination,
            persona,
            query_hint,
            emit_step=emit_step,
        )

    def search_candidate_pois(self, destination: str, persona: dict[str, Any], query_hint: str) -> list[dict[str, Any]]:
        return self._map_data_support.search_candidate_pois(destination, persona, query_hint)

    @staticmethod
    def _map_cache_key(destination: str, persona: dict[str, Any], query_hint: str) -> str:
        return AmapMapDataSupport.map_cache_key(destination, persona, query_hint)

    def build_route_geometry(self, day_pois: list[dict[str, Any]], route_profile: str = "driving") -> dict[str, Any]:
        from backend.planning.route_geometry import DayRoutePlanner

        dest_hint = str((day_pois[0] or {}).get("city", "")).strip() if day_pois else ""
        planner = DayRoutePlanner(_AmapRouteAdapter(self), self.amap)
        return planner.plan(day_pois, route_profile=route_profile, destination_hint=dest_hint).to_dict()

    @staticmethod
    def _extract_direction_paths(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """提取高德路线结果中的路径列表。"""
        return extract_direction_paths(payload)

    def _decode_polyline_string(self, raw: str) -> list[list[float]]:
        return decode_polyline_string(
            raw,
            parse_lnglat_fn=self.parse_lnglat,
            order_lng_lat_fn=self._order_lng_lat,
        )

    def _polyline_points_from_path(self, path: dict[str, Any]) -> list[list[float]]:
        """从单条路径中提取可绘制折线。"""
        return polyline_points_from_path(
            path,
            parse_lnglat_fn=self.parse_lnglat,
            order_lng_lat_fn=self._order_lng_lat,
        )

    def _parse_route_segment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return parse_route_segment(payload, parse_lnglat_fn=self.parse_lnglat)

    @staticmethod
    def _order_lng_lat(first: float, second: float) -> tuple[float, float]:
        """纠正经纬度顺序。"""
        return order_lng_lat(first, second)

    @staticmethod
    def parse_lnglat(value: str) -> tuple[float, float] | None:
        return geo_parse_lnglat(value)

    @staticmethod
    def distance_km(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
        return geo_distance_km(a, b)

    @staticmethod
    def guess_tags(name: str, type_text: str = "") -> list[str]:
        tags = infer_poi_tags(name, type_text)
        return tags or ["经典热门"]

    @staticmethod
    def _build_condition(day_weather: str, night_weather: str) -> str:
        from backend.tools.amap_weather import build_condition

        return build_condition(day_weather, night_weather)

    @staticmethod
    def _extract_forecast_reporttime(payload: dict[str, Any]) -> str:
        return extract_forecast_reporttime(payload)

    def _normalize_weather_payload(self, destination: str, dates: list[str], payload: dict[str, Any]) -> list[dict[str, Any]]:
        return normalize_weather_payload(destination, dates, payload)

    @staticmethod
    def _unwrap_poi_record(payload: Any) -> dict[str, Any]:
        """MCP/REST 详情可能为 {pois:[{...}]} 或扁平 dict。"""
        if not isinstance(payload, dict):
            return {}
        pois = payload.get("pois")
        if isinstance(pois, list) and pois and isinstance(pois[0], dict):
            return dict(pois[0])
        return dict(payload)

    @staticmethod
    def _coord_string_from_record(record: dict[str, Any], *keys: str) -> str:
        return AmapPoiCoordinateSupport.coord_string_from_record(record, *keys)

    def _geocode_address_line(self, query: str, city_hint: str = "") -> str:
        return self._poi_coordinate_support.geocode_address_line(query, city_hint)

    @staticmethod
    def _should_prefer_address_anchor(name: str, address: str) -> bool:
        """临江景点或大范围景区优先使用地址锚点。"""
        return AmapPoiCoordinateSupport.should_prefer_address_anchor(name, address)

    @classmethod
    def _should_resolve_search_coordinate(cls, row: dict[str, Any], name: str, address: str) -> bool:
        """判断搜索坐标是否需要重解析。"""
        return AmapPoiCoordinateSupport.should_resolve_search_coordinate(row, name, address)

    @staticmethod
    def _format_location(pair: tuple[float, float]) -> str:
        return AmapPoiCoordinateSupport.format_location(pair)

    @staticmethod
    def _in_china_bbox(lng: float, lat: float) -> bool:
        return AmapPoiCoordinateSupport.in_china_bbox(lng, lat)

    @classmethod
    def _wgs84_to_gcj02(cls, lng: float, lat: float) -> tuple[float, float]:
        return AmapPoiCoordinateSupport.wgs84_to_gcj02(lng, lat)

    def _geocode_poi_queries(self, name: str, address: str, city: str, province: str = "") -> list[tuple[str, str]]:
        return self._poi_coordinate_support.geocode_poi_queries(name, address, city, province)

    def _collect_poi_coordinate_candidates(
        self,
        row_rec: dict[str, Any],
        detail_rec: dict[str, Any],
        name: str,
        address: str,
        city: str,
    ) -> list[_PoiCoordinateCandidate]:
        return self._poi_coordinate_support.collect_poi_coordinate_candidates(
            row_rec,
            detail_rec,
            name,
            address,
            city,
        )

    def _collect_homonym_search_candidates(self, name: str, city: str, address: str) -> list[_PoiCoordinateCandidate]:
        return self._poi_coordinate_support.collect_homonym_search_candidates(name, city, address)

    @staticmethod
    def _dedupe_coordinate_candidates(candidates: list[_PoiCoordinateCandidate]) -> list[_PoiCoordinateCandidate]:
        return AmapPoiCoordinateSupport.dedupe_coordinate_candidates(candidates)

    def _inspect_regeocode(self, location: str) -> dict[str, Any]:
        return self._poi_coordinate_support.inspect_regeocode(location)

    @staticmethod
    def _poi_name_similarity(expected: str, other: str) -> float:
        return AmapPoiCoordinateSupport.poi_name_similarity(expected, other, TravelResearchTools._dedupe_name_key)

    @classmethod
    def _is_water_like_point(cls, inspection: dict[str, Any], poi_name: str) -> bool:
        return AmapPoiCoordinateSupport.is_water_like_point(
            inspection,
            poi_name,
            TravelResearchTools._dedupe_name_key,
        )

    def _land_reference_pair(
        self,
        candidates: list[_PoiCoordinateCandidate],
        inspections: dict[str, dict[str, Any]],
        poi_name: str,
    ) -> tuple[float, float] | None:
        return self._poi_coordinate_support.land_reference_pair(candidates, inspections, poi_name)

    def _score_poi_coordinate_candidate(
        self,
        candidate: _PoiCoordinateCandidate,
        poi_name: str,
        entr_pair: tuple[float, float] | None,
        inspections: dict[str, dict[str, Any]],
    ) -> float:
        return self._poi_coordinate_support.score_poi_coordinate_candidate(
            candidate,
            poi_name,
            entr_pair,
            inspections,
        )

    def _score_with_land_reference(
        self,
        candidate: _PoiCoordinateCandidate,
        poi_name: str,
        entr_pair: tuple[float, float] | None,
        inspections: dict[str, dict[str, Any]],
        land_ref: tuple[float, float] | None,
    ) -> float:
        return self._poi_coordinate_support.score_with_land_reference(
            candidate,
            poi_name,
            entr_pair,
            inspections,
            land_ref,
        )

    def _lookup_osm_coordinate(self, name: str, city: str, address: str = "") -> str:
        return self._poi_coordinate_support.lookup_osm_coordinate(name, city, address)

    def _select_best_poi_coordinate(
        self,
        name: str,
        address: str,
        city: str,
        candidates: list[_PoiCoordinateCandidate],
    ) -> str:
        return self._poi_coordinate_support.select_best_poi_coordinate(name, address, city, candidates)

    def _resolve_poi_coordinate(self, row: dict[str, Any], detail: dict[str, Any] | None, destination: str = "") -> str:
        return self._poi_coordinate_support.resolve_poi_coordinate(row, detail, destination)

    @staticmethod
    def _extract_geocode_location(payload: dict[str, Any]) -> str:
        return extract_geocode_location(payload)

    @staticmethod
    def _extract_geocode_name(payload: dict[str, Any], default: str) -> str:
        return extract_geocode_name(payload, default)

    @staticmethod
    def _extract_geocode_admin1(payload: dict[str, Any]) -> str:
        return extract_geocode_admin1(payload)

    @staticmethod
    def _extract_geocode_adcode(payload: dict[str, Any]) -> str:
        rows = payload.get("geocodes") if isinstance(payload, dict) else None
        if not rows:
            rows = payload.get("results", []) if isinstance(payload, dict) else []
        first = rows[0] if rows and isinstance(rows[0], dict) else {}
        return str(first.get("adcode", "")).strip()

    @staticmethod
    def _extract_destination_scope(payload: dict[str, Any], destination: str) -> dict[str, Any]:
        return extract_destination_scope(payload, destination)

    def _resolve_search_strategy(
        self,
        destination: str,
        persona: dict[str, Any],
        scope: dict[str, Any] | None,
    ) -> SearchStrategy:
        return build_search_strategy(
            destination,
            str(persona.get("travel_style", "经典热门")),
            scope,
            likes=list(persona.get("likes", [])),
        )

    def _build_poi_queries(
        self,
        destination: str,
        persona: dict[str, Any],
        query_hint: str,
        scope: dict[str, Any] | None = None,
        strategy: SearchStrategy | None = None,
    ) -> list[str]:
        return self._poi_research_support.build_poi_queries(
            destination,
            persona,
            query_hint,
            scope,
            strategy,
        )

    @staticmethod
    def _is_complex_sub_poi(name: str, type_text: str) -> bool:
        return is_complex_sub_poi(name, type_text)

    @staticmethod
    def _dedupe_name_key(name: str) -> str:
        return dedupe_name_key(name)

    def _destination_priority_score(
        self,
        destination: str,
        persona: dict[str, Any],
        poi: dict[str, Any],
        strategy: SearchStrategy | None = None,
    ) -> float:
        return self._poi_research_support.destination_priority_score(destination, persona, poi, strategy)

    def _collect_candidate_rows(
        self,
        destination: str,
        persona: dict[str, Any],
        scope: dict[str, Any],
        queries: list[str],
        strategy: SearchStrategy,
    ) -> list[dict[str, Any]]:
        return self._poi_research_support.collect_candidate_rows(destination, persona, scope, queries, strategy)

    def _normalize_pois(
        self,
        rows: list[Any],
        origin_location: str,
        destination: str,
        persona: dict[str, Any],
        scope: dict[str, Any] | None = None,
        strategy: SearchStrategy | None = None,
    ) -> list[dict[str, Any]]:
        return self._poi_research_support.normalize_pois(
            rows,
            origin_location,
            destination,
            persona,
            scope,
            strategy,
        )

    def _enrich_search_rows(self, rows: list[Any], destination: str, *, max_rows: int = 18) -> list[dict[str, Any]]:
        return self._poi_research_support.enrich_search_rows(rows, destination, max_rows=max_rows)

    def _ensure_poi_location(self, poi: dict[str, Any], destination: str = "") -> str:
        return self._poi_research_support.ensure_poi_location(poi, destination)

    @staticmethod
    def _estimate_static_map_zoom(points: list[tuple[float, float]]) -> int:
        return AmapStaticMapSupport.estimate_static_map_zoom(points)

    def build_static_map_preview(self, route_geometry: dict[str, Any], day_pois: list[dict[str, Any]]) -> str:
        return self._static_map_support.build_static_map_preview(route_geometry, day_pois)

    @staticmethod
    def _static_map_label_text(name: str) -> str:
        """清洗静态地图标签文案。"""
        return AmapStaticMapSupport.static_map_label_text(name)

    @staticmethod
    def _is_usable_poi(row: dict[str, Any]) -> bool:
        return AmapPoiResearchSupport.is_usable_poi(row)

    def _fallback_route_geometry(self, day_pois: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        return self._poi_research_support.fallback_route_geometry(day_pois, reason)

    @staticmethod
    def _fallback_weather(destination: str, dates: list[str], reason: str) -> dict[str, Any]:
        return fallback_weather_payload(destination, dates, reason)

    def _fallback_map(self, destination: str, reason: str, query_hint: str = "") -> dict[str, Any]:
        return self._map_data_support.fallback_map(destination, reason, query_hint)
