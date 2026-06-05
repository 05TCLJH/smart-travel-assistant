"""景点检索子系统：由策略、管道与过滤组成，并与高德调用解耦。

包级不做重导出，避免与景区归并和归一化模块循环依赖；请从子模块显式导入。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "PoiRetrievalPipeline",
    "PoiRetrievalPolicy",
    "SPATIAL_CITY_LOCAL",
    "SPATIAL_WIDE_AREA",
    "build_fallback_map_payload",
    "build_poi_queries",
    "normalize_pois",
    "supplement_with_demo_pois",
]


def __getattr__(name: str) -> Any:
    if name == "PoiRetrievalPipeline":
        from backend.planning.poi_retrieval.pipeline import PoiRetrievalPipeline

        return PoiRetrievalPipeline
    if name == "PoiRetrievalPolicy":
        from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy

        return PoiRetrievalPolicy
    if name in {"SPATIAL_CITY_LOCAL", "SPATIAL_WIDE_AREA"}:
        from backend.planning.poi_retrieval import policy as _policy

        return getattr(_policy, name)
    if name == "normalize_pois":
        from backend.planning.poi_retrieval.normalizer import normalize_pois

        return normalize_pois
    if name == "build_poi_queries":
        from backend.planning.poi_retrieval.query_builder import build_poi_queries

        return build_poi_queries
    if name == "build_fallback_map_payload":
        from backend.planning.poi_retrieval.fallback import build_fallback_map_payload

        return build_fallback_map_payload
    if name == "supplement_with_demo_pois":
        from backend.planning.poi_retrieval.fallback import supplement_with_demo_pois

        return supplement_with_demo_pois
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
