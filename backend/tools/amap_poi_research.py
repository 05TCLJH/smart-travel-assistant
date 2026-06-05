"""高德景点检索支撑模块。

负责检索查询构造、候选行收集、景点归一化、搜索结果补全、坐标补齐与路线失败回退。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from backend.planning.poi_retrieval.classifiers import is_usable_raw_poi
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.planning.poi_retrieval.priority import destination_priority_score
from backend.planning.search_strategy import SearchStrategy


class AmapPoiResearchSupport:
    """景点检索与补全支撑器。"""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def build_poi_queries(
        self,
        destination: str,
        persona: dict[str, Any],
        query_hint: str,
        scope: dict[str, Any] | None = None,
        strategy: SearchStrategy | None = None,
    ) -> list[str]:
        """构建当前目的地的景点查询词。"""
        active = strategy or self._owner._resolve_search_strategy(destination, persona, scope)
        queries, _ = self._owner._poi_pipeline.build_queries(destination, persona, query_hint, scope, active)
        return queries

    def collect_candidate_rows(
        self,
        destination: str,
        persona: dict[str, Any],
        scope: dict[str, Any],
        queries: list[str],
        strategy: SearchStrategy,
    ) -> list[dict[str, Any]]:
        """按当前策略收集候选原始行。"""
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        return self._owner._poi_pipeline.collect_rows(destination, persona, scope, queries, policy)

    def normalize_pois(
        self,
        rows: list[Any],
        origin_location: str,
        destination: str,
        persona: dict[str, Any],
        scope: dict[str, Any] | None = None,
        strategy: SearchStrategy | None = None,
    ) -> list[dict[str, Any]]:
        """将原始检索结果归一化为规划可用景点。"""
        active = strategy or self._owner._resolve_search_strategy(destination, persona, scope)
        return self._owner._poi_pipeline.normalize(rows, origin_location, destination, persona, scope, active)

    def enrich_search_rows(self, rows: list[Any], destination: str, *, max_rows: int = 18) -> list[dict[str, Any]]:
        """补充搜索行的坐标、地址和评分字段（并行化）。"""
        limit = max(6, int(max_rows or 18))
        source_rows = [dict(r) for r in (rows[:limit] if isinstance(rows, list) else []) if isinstance(r, dict)]
        if not source_rows:
            return []

        def _enrich_one(row: dict[str, Any]) -> dict[str, Any]:
            current = dict(row)
            poi_id = str(current.get("id", "")).strip()
            existing_loc = str(current.get("location", "")).strip()
            detail: dict[str, Any] = {}
            if poi_id and not existing_loc:
                try:
                    detail = self._owner.amap.search_detail(poi_id)
                except Exception:
                    detail = {}
            if existing_loc and not detail:
                current["location"] = existing_loc
            else:
                current["location"] = self._owner._resolve_poi_coordinate(current, detail, destination) or existing_loc
            current["address"] = str(current.get("address") or detail.get("address") or "").strip()
            current["cityname"] = str(current.get("cityname") or detail.get("city") or destination).strip()
            current["pname"] = str(current.get("pname") or detail.get("province") or "").strip()
            current["adname"] = str(current.get("adname") or detail.get("district") or "").strip()
            current["type"] = str(current.get("type") or detail.get("type") or current.get("typecode") or "").strip()
            current["biz_ext"] = {
                "rating": str((current.get("biz_ext") or {}).get("rating") or detail.get("rating") or ""),
                "cost": str((current.get("biz_ext") or {}).get("cost") or detail.get("cost") or ""),
            }
            return current

        enriched: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(_enrich_one, row): idx for idx, row in enumerate(source_rows)}
            results: dict[int, dict[str, Any]] = {}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception:
                    results[idx] = source_rows[idx]
            enriched = [results[i] for i in sorted(results)]
        return enriched

    def ensure_poi_location(self, poi: dict[str, Any], destination: str = "") -> str:
        """确保景点拥有可解析的坐标。"""
        existing_location = str(poi.get("location", "")).strip()
        if self._owner.parse_lnglat(existing_location):
            return existing_location
        poi_id = str(poi.get("poi_id", "") or poi.get("id", "")).strip()
        detail: dict[str, Any] = {}
        if poi_id and self._owner.amap.enabled:
            try:
                detail = self._owner.amap.search_detail(poi_id)
            except Exception:
                detail = {}
        detail_rec = self._owner._unwrap_poi_record(detail)
        row = {
            "name": poi.get("name", ""),
            "address": poi.get("address", ""),
            "cityname": poi.get("city", ""),
            "pname": poi.get("province", ""),
            "location": poi.get("location", ""),
            "entr_location": detail_rec.get("entr_location", ""),
            "exit_location": detail_rec.get("exit_location", ""),
            "id": poi_id,
        }
        resolved = self._owner._resolve_poi_coordinate(row, detail_rec, destination or str(poi.get("city", "")))
        return resolved or str(poi.get("location", "")).strip()

    @staticmethod
    def is_usable_poi(row: dict[str, Any]) -> bool:
        """判断原始行是否适合作为候选景点。"""
        return is_usable_raw_poi(row)

    def fallback_route_geometry(self, day_pois: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        """在路线规划失败时生成无折线的兜底路线结果。"""
        dest_hint = str((day_pois[0] or {}).get("city", "")).strip() if day_pois else ""
        from backend.planning.route_geometry import DayRoutePlanner
        from backend.tools.amap_route import _AmapRouteAdapter

        planner = DayRoutePlanner(_AmapRouteAdapter(self._owner), self._owner.amap)
        result = planner.plan(day_pois, route_profile="driving", destination_hint=dest_hint)
        payload = result.to_dict()
        if reason:
            payload["message"] = reason
        if payload.get("status") == "metrics_only" and reason:
            payload["status"] = "failed"
        payload["polyline"] = []
        payload["draw_path"] = False
        return payload

    def destination_priority_score(
        self,
        destination: str,
        persona: dict[str, Any],
        poi: dict[str, Any],
        strategy: SearchStrategy | None = None,
    ) -> float:
        """计算景点对当前目的地的优先级分。"""
        active = strategy or self._owner._resolve_search_strategy(destination, persona, None)
        return destination_priority_score(PoiRetrievalPolicy.from_strategy(active), poi)
