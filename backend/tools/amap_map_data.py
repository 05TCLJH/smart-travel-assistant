"""高德地图数据编排支撑模块。

负责地图数据缓存键、地图主流程编排、候选景点查询与地图兜底结果构建。
"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from collections.abc import Callable
from typing import Any

from backend.core.settings import env_float
from backend.knowledge.destination_catalog import resolve_geocode_query
from backend.planning.poi_retrieval.fallback import build_fallback_map_payload, supplement_with_demo_pois
from backend.planning.poi_retrieval.normalizer import pick_primary_city
from backend.planning.search_strategy import enrich_scope_with_strategy
from backend.planning.visit_sites import dedupe_by_scenic_cluster, seed_names_from_persona
from backend.tools.amap_common import amap_failure_followup_hint, safe_float


class AmapMapDataSupport:
    """地图数据编排支撑器。"""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    @staticmethod
    def map_cache_key(destination: str, persona: dict[str, Any], query_hint: str, scope_key: str = "") -> str:
        """构造地图数据缓存键。"""
        hotspots = [
            str(item).strip()
            for item in (persona.get("destination_hotspots", []) or [])[:6]
            if str(item).strip()
        ]
        likes = [
            str(item).strip()
            for item in (persona.get("likes", []) or [])[:4]
            if str(item).strip()
        ]
        return json.dumps(
            {
                "destination": str(destination or "").strip(),
                "style_key": str(persona.get("style_key", "")).strip(),
                "travel_style": str(persona.get("travel_style", "")).strip(),
                "query_hint": str(query_hint or "").strip(),
                "scope_key": str(scope_key or "").strip(),
                "likes": likes,
                "hotspots": hotspots,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def build_map_data(
        self,
        destination: str,
        persona: dict[str, Any],
        query_hint: str = "",
        *,
        emit_step: Callable[[str, str, str | None], None] | None = None,
    ) -> dict[str, Any]:
        """执行地图数据采集、检索与结果组装主流程。"""

        def _emit(step_id: str, status: str, detail: str | None = None) -> None:
            if emit_step is not None:
                emit_step(step_id, status, detail)

        cache_key = self.map_cache_key(destination, persona, query_hint, self._owner.amap.server_url)
        cache_ttl = env_float("AMAP_MAP_DATA_CACHE_SECONDS", 900.0)
        cached = self._owner._map_data_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] <= cache_ttl:
            return deepcopy(cached[1])

        if not (self._owner.mcp_enabled and self._owner.amap.enabled):
            return self.fallback_map(destination, "当前为体验模式或未配置高德 MCP", query_hint=query_hint)

        try:
            _emit("research.geocode", "running", f"地理编码：{destination}")
            geocode_query = resolve_geocode_query(destination)
            geo = self._owner.amap.geocode(geocode_query)
            location = self._owner._extract_geocode_location(geo)
            if not location:
                raise RuntimeError("高德 MCP geocode 未返回坐标")
            scope = self._owner._extract_destination_scope(geo, destination)
            scope["geocode_query"] = geocode_query
            strategy = self._owner._resolve_search_strategy(destination, persona, scope)
            scope = enrich_scope_with_strategy(scope, strategy)
            resolved_name = str(scope.get("resolved_name", "")).strip() or self._owner._extract_geocode_name(geo, destination)
            _emit("research.geocode", "done", f"已定位：{resolved_name}")
            pois, search_queries = self._owner._poi_pipeline.run(
                destination=destination,
                persona=persona,
                query_hint=query_hint,
                scope=scope,
                strategy=strategy,
                origin_location=location,
                emit_step=emit_step,
            )
            if not pois:
                raise RuntimeError(
                    "高德 MCP 文本搜索未返回任何 POI（接口未报错但结果为空）。"
                    "请尝试更完整的城市名、检查 citylimit 与目的地是否一致；若控制台显示调用成功但始终为空，请联系高德侧排查。"
                )
        except Exception as exc:
            return self.fallback_map(destination, str(exc), query_hint=query_hint)

        pois = supplement_with_demo_pois(destination, persona, pois, query_hint)
        pois = dedupe_by_scenic_cluster(list(pois), seed_names=seed_names_from_persona(persona), max_per_cluster=1)
        cluster_city = pick_primary_city(pois)
        transport_hint = "已按当前行程范围优先整理候选景点。"
        if strategy.destination_kind == "province" and cluster_city:
            transport_hint = f"{transport_hint} 当前为省级目的地，已优先收敛到 {cluster_city} 城市圈，避免行程跨城过散。"
        if strategy.destination_kind == "scenic_region":
            transport_hint = f"{transport_hint} 当前为风景环线目的地，候选覆盖区域内多个县市。"

        payload = {
            "destination": destination,
            "resolved_name": resolved_name,
            "geo": {
                "lng": safe_float(location.split(",")[0] if "," in location else 0.0, 0.0),
                "lat": safe_float(location.split(",")[1] if "," in location else 0.0, 0.0),
            },
            "country": "中国",
            "admin1": str(scope.get("province", "")).strip() or self._owner._extract_geocode_admin1(geo),
            "pois": pois,
            "transport_hint": transport_hint,
            "provider": "amap-mcp",
            "is_fallback": False,
            "search_query": " | ".join(search_queries),
            "planning_scope": {
                "is_province_level": bool(scope.get("is_province_level")),
                "cluster_city": cluster_city,
            },
        }
        self._owner._map_data_cache[cache_key] = (time.monotonic(), deepcopy(payload))
        if len(self._owner._map_data_cache) > 64:
            oldest_key = min(self._owner._map_data_cache.items(), key=lambda item: item[1][0])[0]
            self._owner._map_data_cache.pop(oldest_key, None)
        return payload

    def search_candidate_pois(self, destination: str, persona: dict[str, Any], query_hint: str) -> list[dict[str, Any]]:
        """仅返回地图主流程中的候选景点列表。"""
        map_data = self.build_map_data(destination, persona, query_hint=query_hint)
        return list(map_data.get("pois", []) or [])

    def fallback_map(self, destination: str, reason: str, query_hint: str = "") -> dict[str, Any]:
        """构造地图检索失败时的兜底返回。"""

        def format_warning(current_reason: str) -> str:
            tail = ""
            if current_reason and "演示" not in current_reason and "体验模式" not in current_reason and "未配置高德 MCP" not in current_reason:
                tail = amap_failure_followup_hint(current_reason)
            return f"{current_reason}{tail}".strip() if current_reason else "已回退到本地演示数据。"

        return build_fallback_map_payload(
            destination,
            query_hint=query_hint,
            reason=reason,
            warning_formatter=format_warning,
        )
