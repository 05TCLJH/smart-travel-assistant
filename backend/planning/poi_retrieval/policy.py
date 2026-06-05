"""景点检索策略：由搜索策略派生，驱动查询构建与过滤管道。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.planning.search_strategy import SearchStrategy

SPATIAL_CITY_LOCAL = "city_local"
SPATIAL_WIDE_AREA = "wide_area"


@dataclass(frozen=True)
class PoiRetrievalPolicy:
    """检索与归一化的唯一策略对象，避免在执行层散落 if/else。"""

    destination: str
    style_key: str
    spatial_mode: str
    search_radius_km: float
    restrict_to_single_city: bool
    apply_city_museum_filters: bool
    seed_poi_names: tuple[str, ...]
    exact_query_names: frozenset[str]
    priority_rules: dict[str, list[str]]
    max_query_count: int
    allow_wide_area_museums: bool
    city_local_max_distance_km: float = 20.0

    @property
    def is_wide_area(self) -> bool:
        return self.spatial_mode == SPATIAL_WIDE_AREA

    @classmethod
    def from_strategy(cls, strategy: SearchStrategy) -> PoiRetrievalPolicy:
        exact: set[str] = set(strategy.build_direct_queries())
        for names in (strategy.priority_rules or {}).values():
            exact.update(str(n).strip() for n in names if str(n).strip())
        for seed in strategy.seed_poi_names:
            text = str(seed).strip()
            if text:
                exact.add(text)
        spatial = SPATIAL_WIDE_AREA if strategy.wide_area_search else SPATIAL_CITY_LOCAL
        radius = float(strategy.search_radius_km)
        # 城市检索半径常设为 35 公里，旧默认 20 公里会把磁器口、南山等近郊景点误杀。
        city_local_km = radius if spatial == SPATIAL_CITY_LOCAL else 20.0
        return cls(
            destination=strategy.destination,
            style_key=strategy.style_key,
            spatial_mode=spatial,
            search_radius_km=radius,
            restrict_to_single_city=bool(strategy.restrict_to_single_city),
            apply_city_museum_filters=bool(strategy.apply_city_museum_filters),
            seed_poi_names=tuple(strategy.seed_poi_names),
            exact_query_names=frozenset(exact),
            priority_rules=dict(strategy.priority_rules or {}),
            max_query_count=int(strategy.max_query_count),
            allow_wide_area_museums=strategy.style_key == "cultural",
            city_local_max_distance_km=min(city_local_km, 55.0),
        )

    def is_exact_query(self, query: str) -> bool:
        text = str(query or "").strip()
        if not text:
            return False
        if text in self.exact_query_names:
            return True
        return any(seed and (seed in text or text in seed) for seed in self.exact_query_names)

    def seed_name_set(self) -> set[str]:
        return {str(s).strip() for s in self.seed_poi_names if str(s).strip()}
