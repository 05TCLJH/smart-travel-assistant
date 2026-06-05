"""兼容层：景区簇接口已迁至游览点归并模块。"""

from __future__ import annotations

from backend.planning.visit_sites import (
    address_venue_key,
    cluster_key_for_poi,
    dedupe_by_scenic_cluster,
    merge_to_visit_sites,
    scenic_cluster_key,
    seed_names_from_persona,
    visit_site_id,
)

__all__ = [
    "address_venue_key",
    "cluster_key_for_poi",
    "dedupe_by_scenic_cluster",
    "merge_to_visit_sites",
    "scenic_cluster_key",
    "seed_names_from_persona",
    "visit_site_id",
]
