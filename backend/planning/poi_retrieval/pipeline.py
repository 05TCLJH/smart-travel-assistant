"""景点检索管道：地理编码之后的查询、采集与归一化。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from backend.planning.poi_retrieval.collector import collect_candidate_rows, select_rows_for_enrichment
from backend.planning.poi_retrieval.seed_coverage import ensure_catalog_seed_rows
from backend.planning.poi_retrieval.coordinate import CoordinateResolver
from backend.planning.poi_retrieval.normalizer import normalize_pois
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.planning.poi_retrieval.priority import destination_priority_score
from backend.planning.poi_retrieval.query_builder import build_poi_queries
from backend.planning.planning_profile import resolve_planning_profile
from backend.planning.search_strategy import SearchStrategy

if TYPE_CHECKING:
    from backend.tools.amap_tools import TravelResearchTools


class AmapCoordinateResolver:
    """将 TravelResearchTools 的坐标能力适配为 CoordinateResolver。"""

    def __init__(self, tools: TravelResearchTools) -> None:
        self._tools = tools

    def should_resolve_search_coordinate(self, row: dict[str, Any], name: str, address: str) -> bool:
        return self._tools._should_resolve_search_coordinate(row, name, address)

    def resolve_poi_coordinate(self, row: dict[str, Any], detail: dict[str, Any] | None, destination: str) -> str:
        return self._tools._resolve_poi_coordinate(row, detail, destination) or ""


class PoiRetrievalPipeline:
    """POI 检索编排器；TravelResearchTools 仅保留高德 IO 与坐标精修。"""

    def __init__(self, tools: TravelResearchTools) -> None:
        self._tools = tools
        self._coords = AmapCoordinateResolver(tools)

    def build_queries(
        self,
        destination: str,
        persona: dict[str, Any],
        query_hint: str,
        scope: dict[str, Any] | None,
        strategy: SearchStrategy,
    ) -> tuple[list[str], PoiRetrievalPolicy]:
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        queries = build_poi_queries(destination, persona, query_hint, strategy, policy)
        return queries, policy

    def collect_rows(
        self,
        destination: str,
        persona: dict[str, Any],
        scope: dict[str, Any],
        queries: list[str],
        policy: PoiRetrievalPolicy,
    ) -> list[dict[str, Any]]:
        diversified = collect_candidate_rows(
            self._tools.amap,
            destination,
            scope,
            queries,
            policy,
            priority_score_fn=lambda poi: destination_priority_score(policy, poi),
        )
        diversified = ensure_catalog_seed_rows(
            diversified,
            self._tools.amap,
            destination,
            scope,
            policy,
        )
        planning_profile = resolve_planning_profile(
            persona,
            is_wide_area=policy.is_wide_area,
            seed_count=len(policy.seed_name_set()),
        )
        enrich_limit = planning_profile.enrichment_limit
        selected = select_rows_for_enrichment(diversified, policy, max_total=enrich_limit)
        return self._tools._enrich_search_rows(selected, destination, max_rows=enrich_limit)

    def normalize(
        self,
        rows: list[Any],
        origin_location: str,
        destination: str,
        persona: dict[str, Any],
        scope: dict[str, Any] | None,
        strategy: SearchStrategy,
    ) -> list[dict[str, Any]]:
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        return normalize_pois(rows, origin_location, destination, persona, scope, policy, self._coords)

    def run(
        self,
        *,
        destination: str,
        persona: dict[str, Any],
        query_hint: str,
        scope: dict[str, Any],
        strategy: SearchStrategy,
        origin_location: str,
        emit_step: Callable[[str, str, str | None], None] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        def _emit(step_id: str, status: str, detail: str | None = None) -> None:
            if emit_step is not None:
                emit_step(step_id, status, detail)

        _emit("research.poi_search", "running", f"按策略检索 {destination} 候选景点…")
        queries, policy = self.build_queries(destination, persona, query_hint, scope, strategy)
        rows = self.collect_rows(destination, persona, scope, queries, policy)
        _emit("research.poi_search", "done", f"检索完成，原始候选 {len(rows)} 条")
        if policy.is_wide_area:
            _emit("research.poi_cluster", "running", "合并同一景区多个高德 POI（入口/停车场/子景点）…")
        _emit("research.poi_normalize", "running", "坐标校正、范围与质量过滤…")
        pois = normalize_pois(rows, origin_location, destination, persona, scope, policy, self._coords)
        _emit("research.poi_normalize", "done", f"过滤后 {len(pois)} 条候选")
        knowledge_hits = sum(1 for poi in pois if poi.get("activity_load_source") == "knowledge")
        if pois:
            sample = next((p for p in pois if p.get("activity_load_source") == "knowledge"), pois[0])
            tier = sample.get("activity_tier_label") or sample.get("activity_tier") or "常规"
            hours = sample.get("visit_hours", "")
            _emit(
                "research.poi_activity_load",
                "done",
                f"已标注 {len(pois)} 个候选体力值（知识库 {knowledge_hits} 个）；示例「{sample.get('name', '')}」{tier}"
                + (f" · 约{hours}h" if hours else ""),
            )
        else:
            _emit("research.poi_activity_load", "done", "无候选，跳过活动负荷标注")
        if policy.is_wide_area:
            from backend.planning.visit_sites import cluster_key_for_poi

            cluster_ids = {cluster_key_for_poi(poi, policy.seed_name_set()) for poi in pois}
            _emit(
                "research.poi_cluster",
                "done",
                f"景区簇去重完成：{len(rows)} 条原始 POI → {len(cluster_ids)} 个不同景区",
            )
        return pois, queries
