"""高德景点坐标解析支撑模块。

负责景点坐标候选收集、水面误定位识别、坐标打分与兜底解析，降低主工具类的复杂度。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from backend.core.settings import env_float
from backend.tools.amap_common import safe_float
from backend.tools.amap_geocode import extract_geocode_location


POI_COORD_SOURCE_WEIGHT: dict[str, float] = {
    "entr": 100.0,
    "exit": 92.0,
    "geocode_address_name": 78.0,
    "geocode_address": 74.0,
    "geocode_name": 55.0,
    "homonym_entr": 96.0,
    "homonym_search": 36.0,
    "osm": 62.0,
    "search": 32.0,
}

COORD_LAND_REFERENCE_SOURCES = ("entr", "exit", "geocode_address", "geocode_address_name", "homonym_entr")
WATER_REGEOCODE_HINTS = ("江心", "河中", "河心", "湖面", "湖心", "水面", "水中", "海上", "海域", "水道", "运河")
WATER_POI_TYPE_TOKENS = ("水系", "河流", "湖泊", "海域", "水库", "运河", "水道")
RIVERSIDE_LANDMARK_NAME_TOKENS = ("阁", "楼", "台", "亭", "塔", "寺", "庙", "宫", "故居", "纪念馆", "博物馆")
RIVERSIDE_TOWER_NAME_TOKENS = ("阁", "楼", "台", "亭", "塔")
WATER_POI_NAME_EXCEPTIONS = ("江滩", "滨江", "湖畔", "海边", "湖滨", "码头", "渡口", "湿地", "公园")


@dataclass(frozen=True)
class _PoiCoordinateCandidate:
    """景点坐标候选项。"""

    location: str
    source: str


class AmapPoiCoordinateSupport:
    """景点坐标解析支撑器。"""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    @staticmethod
    def coord_string_from_record(record: dict[str, Any], *keys: str) -> str:
        """从记录中读取第一个合法坐标字符串。"""
        for key in keys:
            raw = str(record.get(key, "")).strip()
            if raw and "," in raw:
                return raw
        return ""

    def geocode_address_line(self, query: str, city_hint: str = "") -> str:
        """对地址文本做地理编码并返回坐标。"""
        text = str(query or "").strip()
        if not text or not (self._owner.mcp_enabled and self._owner.amap.enabled):
            return ""
        if city_hint and city_hint not in text:
            text = f"{city_hint}{text}"
        payload = self._owner.resolve_geocode_payload(text)
        return extract_geocode_location(payload) if payload else ""

    @staticmethod
    def should_prefer_address_anchor(name: str, address: str) -> bool:
        """判断是否更应优先使用地址锚点，而不是搜索质心。"""
        if any(token in address for token in ("路", "街", "号", "大道", "弄", "巷")):
            return True
        if any(token in name for token in ("阁", "楼", "台", "亭", "塔", "寺", "庙", "宫", "园", "景区", "广场", "街区", "纪念馆", "博物馆")):
            return True
        return False

    @classmethod
    def should_resolve_search_coordinate(cls, row: dict[str, Any], name: str, address: str) -> bool:
        """判断搜索坐标是否需要重新解析。"""
        if cls.coord_string_from_record(row, "entr_location", "exit_location"):
            return True
        return cls.should_prefer_address_anchor(name, address)

    @staticmethod
    def format_location(pair: tuple[float, float]) -> str:
        """把经纬度元组格式化为坐标字符串。"""
        return f"{pair[0]:.6f},{pair[1]:.6f}"

    @staticmethod
    def in_china_bbox(lng: float, lat: float) -> bool:
        """判断坐标是否位于中国常用范围内。"""
        return 72.0 <= lng <= 138.0 and 16.0 <= lat <= 55.0

    @classmethod
    def wgs84_to_gcj02(cls, lng: float, lat: float) -> tuple[float, float]:
        """把 WGS84 坐标转换为 GCJ-02 坐标。"""
        if not cls.in_china_bbox(lng, lat):
            return lng, lat

        def transform_lat(x: float, y: float) -> float:
            ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
            ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
            ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
            ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
            return ret

        def transform_lng(x: float, y: float) -> float:
            ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
            ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
            ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
            ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
            return ret

        a = 6378245.0
        ee = 0.00669342162296594323
        dlat = transform_lat(lng - 105.0, lat - 35.0)
        dlng = transform_lng(lng - 105.0, lat - 35.0)
        radlat = lat / 180.0 * math.pi
        magic = math.sin(radlat)
        magic = 1 - ee * magic * magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
        dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
        return lng + dlng, lat + dlat

    def geocode_poi_queries(self, name: str, address: str, city: str, province: str = "") -> list[tuple[str, str]]:
        """生成并执行景点地理编码查询，返回去重后的候选坐标。"""
        city = str(city or "").strip() or "南昌"
        province = str(province or "").strip()
        cache_key = f"{self._owner.amap.server_url}|{name}|{address}|{city}|{province}"
        cached = self._owner._poi_geocode_query_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        prefix = province or ""
        queries: list[tuple[str, str]] = []
        if address and name:
            queries.append((f"{prefix}{city}{address}{name}", "geocode_address_name"))
        if address:
            queries.append((f"{prefix}{city}{address}", "geocode_address"))
        if name:
            queries.append((f"{prefix}{city}{name}", "geocode_name"))
        seen_query: set[str] = set()
        seen_loc: set[str] = set()
        results: list[tuple[str, str]] = []
        for query, source in queries:
            if query in seen_query:
                continue
            seen_query.add(query)
            loc = self.geocode_address_line(query, city)
            if not loc or loc in seen_loc:
                continue
            seen_loc.add(loc)
            results.append((loc, source))
        self._owner._poi_geocode_query_cache[cache_key] = list(results)
        return results

    def collect_poi_coordinate_candidates(
        self,
        row_rec: dict[str, Any],
        detail_rec: dict[str, Any],
        name: str,
        address: str,
        city: str,
    ) -> list[_PoiCoordinateCandidate]:
        """收集单个景点的多源坐标候选。"""
        candidates: list[_PoiCoordinateCandidate] = []
        province = str(row_rec.get("pname") or detail_rec.get("pname") or "").strip()

        entr = self.coord_string_from_record(row_rec, "entr_location") or self.coord_string_from_record(detail_rec, "entr_location")
        exit_loc = self.coord_string_from_record(row_rec, "exit_location") or self.coord_string_from_record(detail_rec, "exit_location")
        search_loc = self.coord_string_from_record(row_rec, "location") or self.coord_string_from_record(detail_rec, "location")

        if entr:
            candidates.append(_PoiCoordinateCandidate(entr, "entr"))
        if exit_loc:
            candidates.append(_PoiCoordinateCandidate(exit_loc, "exit"))

        if address and self.should_prefer_address_anchor(name, address):
            for loc, source in self.geocode_poi_queries(name, address, city, province):
                candidates.append(_PoiCoordinateCandidate(loc, source))
        elif name:
            for loc, source in self.geocode_poi_queries(name, address, city, province):
                candidates.append(_PoiCoordinateCandidate(loc, source))

        if search_loc:
            candidates.append(_PoiCoordinateCandidate(search_loc, "search"))

        candidates.extend(self.collect_homonym_search_candidates(name, city, address))
        return self.dedupe_coordinate_candidates(candidates)

    def collect_homonym_search_candidates(self, name: str, city: str, address: str) -> list[_PoiCoordinateCandidate]:
        """为同名景点补充更多搜索候选坐标。"""
        del address
        target = self._owner._dedupe_name_key(name)
        if not target or not (self._owner.mcp_enabled and self._owner.amap.enabled):
            return []
        cache_key = f"{self._owner.amap.server_url}|{target}|{city}"
        cached = self._owner._poi_homonym_search_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        try:
            response = self._owner.amap.text_search(f"{city}{name}", city=city, extensions="all", offset=15)
        except Exception:
            return []
        rows = response.get("pois", []) if isinstance(response, dict) else []
        extras: list[_PoiCoordinateCandidate] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            row_name = self._owner._dedupe_name_key(str(row.get("name", "")).strip())
            if not row_name or (target not in row_name and row_name not in target):
                continue
            if str(row.get("parent", "") or row.get("parentid", "")).strip():
                continue
            entr = self.coord_string_from_record(row, "entr_location")
            loc = self.coord_string_from_record(row, "location")
            if entr:
                extras.append(_PoiCoordinateCandidate(entr, "homonym_entr"))
            if loc:
                extras.append(_PoiCoordinateCandidate(loc, "homonym_search"))
        self._owner._poi_homonym_search_cache[cache_key] = list(extras)
        return extras

    @staticmethod
    def dedupe_coordinate_candidates(candidates: list[_PoiCoordinateCandidate]) -> list[_PoiCoordinateCandidate]:
        """按坐标去重，保留来源权重更高的候选。"""
        best: dict[str, _PoiCoordinateCandidate] = {}
        for item in candidates:
            loc = str(item.location or "").strip()
            if not loc or "," not in loc:
                continue
            existing = best.get(loc)
            if existing is None or POI_COORD_SOURCE_WEIGHT.get(item.source, 0) > POI_COORD_SOURCE_WEIGHT.get(existing.source, 0):
                best[loc] = item
        return list(best.values())

    def inspect_regeocode(self, location: str) -> dict[str, Any]:
        """查询并缓存逆地理结果。"""
        loc = str(location or "").strip()
        if not loc:
            return {}
        cache_key = f"{self._owner.amap.server_url}|{loc}"
        cached = self._owner._regeocode_cache.get(cache_key)
        if cached is not None:
            return cached
        empty: dict[str, Any] = {
            "formatted_address": "",
            "nearest_poi": "",
            "nearest_type": "",
            "nearest_distance": "",
        }
        if not (self._owner.mcp_enabled and self._owner.amap.enabled):
            self._owner._regeocode_cache[cache_key] = empty
            return empty
        try:
            payload = self._owner.amap.regeocode(loc)
            regeocode = payload.get("regeocode") if isinstance(payload, dict) else None
            if not isinstance(regeocode, dict):
                regeocode = payload if isinstance(payload, dict) else {}
            pois = regeocode.get("pois") or []
            nearest = pois[0] if pois and isinstance(pois[0], dict) else {}
            empty = {
                "formatted_address": str(regeocode.get("formatted_address", "")).strip(),
                "nearest_poi": str(nearest.get("name", "")).strip(),
                "nearest_type": str(nearest.get("type", "")).strip(),
                "nearest_distance": str(nearest.get("distance", "")).strip(),
            }
        except Exception:
            pass
        self._owner._regeocode_cache[cache_key] = empty
        return empty

    @staticmethod
    def poi_name_similarity(expected: str, other: str, name_key_fn: Any) -> float:
        """粗略比较目标名与周边名称的一致度。"""
        left = name_key_fn(expected)
        right = name_key_fn(other)
        if not left or not right:
            return 0.0
        if left == right or left in right or right in left:
            return 1.0
        return 0.0

    @classmethod
    def is_water_like_point(cls, inspection: dict[str, Any], poi_name: str, name_key_fn: Any) -> bool:
        """判断候选坐标是否更像落在水面而不是陆地。"""
        name = str(poi_name or "").strip()
        if any(token in name for token in WATER_POI_NAME_EXCEPTIONS):
            return False
        address = str(inspection.get("formatted_address", "")).strip()
        nearest = str(inspection.get("nearest_poi", "")).strip()
        nearest_type = str(inspection.get("nearest_type", "")).strip()
        if any(hint in address for hint in WATER_REGEOCODE_HINTS):
            return True
        if any(token in nearest_type for token in WATER_POI_TYPE_TOKENS):
            return True
        if nearest and cls.poi_name_similarity(name, nearest, name_key_fn) >= 1.0:
            if any(token in nearest_type for token in WATER_POI_TYPE_TOKENS):
                return True
            if address and not any(token in address for token in ("路", "街", "号", "大道", "弄", "巷", "村", "镇", "区")):
                if any(token in address for token in ("江", "河", "湖", "海", "溪", "湾", "水道")):
                    return True
        if nearest and len(nearest) <= 4 and any(token in nearest for token in ("江", "河", "湖", "海", "溪", "湾")):
            if any(token in name for token in RIVERSIDE_LANDMARK_NAME_TOKENS):
                return True
        return False

    def land_reference_pair(
        self,
        candidates: list[_PoiCoordinateCandidate],
        inspections: dict[str, dict[str, Any]],
        poi_name: str,
    ) -> tuple[float, float] | None:
        """优先选取明确落在陆地上的参考坐标。"""
        for source in COORD_LAND_REFERENCE_SOURCES:
            for item in candidates:
                if item.source != source:
                    continue
                pair = self._owner.parse_lnglat(item.location)
                if not pair:
                    continue
                if not self._owner._is_water_like_point(inspections.get(item.location) or {}, poi_name):
                    return pair
        return None

    def score_poi_coordinate_candidate(
        self,
        candidate: _PoiCoordinateCandidate,
        poi_name: str,
        entr_pair: tuple[float, float] | None,
        inspections: dict[str, dict[str, Any]],
    ) -> float:
        """给单个景点坐标候选打分。"""
        pair = self._owner.parse_lnglat(candidate.location)
        if not pair:
            return -999.0
        score = POI_COORD_SOURCE_WEIGHT.get(candidate.source, 30.0)
        inspection = inspections.get(candidate.location) or {}
        if self._owner._is_water_like_point(inspection, poi_name):
            score -= 95.0
        elif (
            not str(inspection.get("formatted_address", "")).strip()
            and candidate.source == "search"
            and any(token in poi_name for token in RIVERSIDE_TOWER_NAME_TOKENS)
            and not any(token in poi_name for token in ("街区", "广场", "公园", "古镇", "古城"))
        ):
            score -= 42.0
        nearest = str(inspection.get("nearest_poi", "")).strip()
        water_like = self._owner._is_water_like_point(inspection, poi_name)
        similarity = self._owner._poi_name_similarity(poi_name, nearest)
        if similarity >= 1.0 and not water_like:
            score += 22.0
        elif similarity > 0 and not water_like:
            score += 10.0
        elif similarity >= 1.0 and water_like:
            score -= 55.0
        if entr_pair:
            gap_km = self._owner.distance_km(pair, entr_pair)
            if candidate.source == "search" and gap_km > 0.18:
                score -= 40.0
            elif candidate.source.startswith("geocode") and gap_km > 0.35:
                score -= 25.0
            elif candidate.source in {"entr", "exit"} and gap_km < 0.05:
                score += 8.0
            elif candidate.source.startswith("geocode") and gap_km < 0.12:
                score += 10.0
        return score

    def score_with_land_reference(
        self,
        candidate: _PoiCoordinateCandidate,
        poi_name: str,
        entr_pair: tuple[float, float] | None,
        inspections: dict[str, dict[str, Any]],
        land_ref: tuple[float, float] | None,
    ) -> float:
        """在基础打分上叠加陆地点参考修正。"""
        score = self._owner._score_poi_coordinate_candidate(candidate, poi_name, entr_pair, inspections)
        if not land_ref:
            return score
        pair = self._owner.parse_lnglat(candidate.location)
        if not pair:
            return score
        gap_km = self._owner.distance_km(pair, land_ref)
        if candidate.source in {"search", "homonym_search", "geocode_name"}:
            if gap_km > 0.22:
                score -= 50.0
            elif gap_km > 0.12:
                score -= 28.0
        elif gap_km < 0.08 and candidate.source in {"entr", "exit", "homonym_entr", "geocode_address"}:
            score += 12.0
        return score

    def lookup_osm_coordinate(self, name: str, city: str, address: str = "") -> str:
        """在高德坐标不可靠时，通过开放地图检索兜底坐标。"""
        if not self._owner.osm_geocode_enabled:
            return ""
        query_key = f"{self._owner.amap.server_url}|{city}|{name}|{address}"
        if query_key in self._owner._osm_cache:
            return self._owner._osm_cache[query_key]
        query = " ".join(part for part in (name, address, city, "中国") if part).strip()
        if not query:
            return ""
        url = (
            "https://nominatim.openstreetmap.org/search?"
            f"q={quote(query)}&format=json&limit=6&countrycodes=cn&addressdetails=0"
        )
        timeout = env_float("OSM_GEOCODE_TIMEOUT_SECONDS", 8.0)
        rows: list[dict[str, Any]] = []
        try:
            request = Request(url, headers={"User-Agent": "SmartTravelAssistant/2.0 (poi-coordinate-fallback)"})
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, list):
                rows = [row for row in payload if isinstance(row, dict)]
        except Exception:
            self._owner._osm_cache[query_key] = ""
            return ""

        preferred_classes = {"tourism", "historic", "amenity", "building", "leisure"}
        penalized_classes = {"railway", "highway", "boundary", "place"}
        best_loc = ""
        best_score = -999.0
        target = self._owner._dedupe_name_key(name)
        for row in rows:
            osm_class = str(row.get("class", "")).strip()
            osm_type = str(row.get("type", "")).strip()
            display = str(row.get("display_name", "")).strip()
            osm_name = str(row.get("name", "")).strip()
            try:
                lat = float(row.get("lat", 0))
                lon = float(row.get("lon", 0))
            except (TypeError, ValueError):
                continue
            lng, lat_g = self._owner._wgs84_to_gcj02(lon, lat)
            item_score = safe_float(row.get("importance"), 0.0) * 40.0
            if osm_class in preferred_classes:
                item_score += 35.0
            if osm_class in penalized_classes:
                item_score -= 45.0
            if osm_type in {"attraction", "museum", "temple", "monument", "viewpoint", "theme_park"}:
                item_score += 20.0
            if target and (target in osm_name or target in display or osm_name in target):
                item_score += 45.0
            if city and city.replace("市", "") not in display:
                item_score -= 20.0
            if item_score > best_score:
                best_score = item_score
                best_loc = self._owner._format_location((lng, lat_g))
        self._owner._osm_cache[query_key] = best_loc
        return best_loc

    def select_best_poi_coordinate(
        self,
        name: str,
        address: str,
        city: str,
        candidates: list[_PoiCoordinateCandidate],
    ) -> str:
        """从候选坐标中选择最可靠的一个。"""
        if not candidates:
            return ""
        entr_pair: tuple[float, float] | None = None
        for item in candidates:
            if item.source == "entr":
                entr_pair = self._owner.parse_lnglat(item.location)
                break

        inspections: dict[str, dict[str, Any]] = {}
        for item in candidates:
            inspections[item.location] = self._owner._inspect_regeocode(item.location)

        land_ref = self._owner._land_reference_pair(candidates, inspections, name)

        ranked = sorted(
            (
                (
                    self._owner._score_with_land_reference(item, name, entr_pair, inspections, land_ref),
                    item,
                )
                for item in candidates
            ),
            key=lambda row: row[0],
            reverse=True,
        )

        viable = [
            (score, item)
            for score, item in ranked
            if not self._owner._is_water_like_point(inspections.get(item.location) or {}, name)
        ]
        if viable:
            ranked = viable
        best_score, best = ranked[0]

        if best_score < 30.0:
            osm_loc = self._owner._lookup_osm_coordinate(name, city, address)
            if osm_loc:
                osm_candidate = _PoiCoordinateCandidate(osm_loc, "osm")
                osm_score = self._owner._score_poi_coordinate_candidate(
                    osm_candidate,
                    name,
                    entr_pair,
                    {osm_loc: self._owner._inspect_regeocode(osm_loc)},
                )
                if osm_score > best_score:
                    return osm_loc

        if entr_pair and best.source in {"search", "homonym_search"} and self._owner.distance_km(self._owner.parse_lnglat(best.location), entr_pair) > 0.15:
            for item in candidates:
                if item.source in {"entr", "homonym_entr"}:
                    return item.location

        for item in candidates:
            if item.source in {"entr", "homonym_entr"}:
                return item.location
        return best.location

    def resolve_poi_coordinate(self, row: dict[str, Any], detail: dict[str, Any] | None, destination: str = "") -> str:
        """解析景点的最终坐标。"""
        row_rec = dict(row or {})
        detail_rec = self._owner._unwrap_poi_record(detail or {})
        name = str(row_rec.get("name", "") or detail_rec.get("name", "")).strip()
        address = str(row_rec.get("address", "") or detail_rec.get("address", "")).strip()
        city = str(row_rec.get("cityname") or row_rec.get("city") or detail_rec.get("city") or destination).strip()
        poi_id = str(row_rec.get("id", "") or detail_rec.get("id", "")).strip()
        cache_key_payload: dict[str, Any] = {
            "destination": str(destination or "").strip(),
            "poi_id": poi_id,
        }
        if not poi_id:
            cache_key_payload["row"] = {
                "name": name,
                "address": address,
                "city": city,
                "province": str(row_rec.get("pname") or row_rec.get("province") or detail_rec.get("pname") or detail_rec.get("province") or "").strip(),
                "location": str(row_rec.get("location", "")).strip(),
                "entr_location": self.coord_string_from_record(row_rec, "entr_location")
                or self.coord_string_from_record(detail_rec, "entr_location"),
                "exit_location": self.coord_string_from_record(row_rec, "exit_location")
                or self.coord_string_from_record(detail_rec, "exit_location"),
                "type": str(row_rec.get("type", "") or detail_rec.get("type", "")).strip(),
                "typecode": str(row_rec.get("typecode", "") or detail_rec.get("typecode", "")).strip(),
            }
        cache_key = json.dumps(
            cache_key_payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        cached = self._owner._poi_coordinate_cache.get(cache_key)
        if cached is not None:
            return cached

        candidates = self._owner._collect_poi_coordinate_candidates(row_rec, detail_rec, name, address, city)
        if candidates:
            resolved = self._owner._select_best_poi_coordinate(name, address, city, candidates)
            self._owner._poi_coordinate_cache[cache_key] = resolved
            return resolved

        osm_loc = self._owner._lookup_osm_coordinate(name, city, address)
        if osm_loc:
            self._owner._poi_coordinate_cache[cache_key] = osm_loc
            return osm_loc
        self._owner._poi_coordinate_cache[cache_key] = ""
        return ""
