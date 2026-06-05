"""知识库目的地覆盖：保证每个热点种子至少有一条高德原始记录进入管道。"""

from __future__ import annotations

from typing import Any

from backend.knowledge.destination_catalog import resolve_destination_key
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.planning.poi_retrieval.query_builder import query_types_for_text


def _seed_represented(seed: str, rows: list[dict[str, Any]]) -> bool:
    text = str(seed or "").strip()
    if not text:
        return True
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        if text in name or (len(name) >= 4 and name in text):
            return True
    return False


def ensure_catalog_seed_rows(
    merged: list[dict[str, Any]],
    amap: Any,
    destination: str,
    scope: dict[str, Any],
    policy: PoiRetrievalPolicy,
) -> list[dict[str, Any]]:
    """对 catalog 目的地补搜未出现在合并池中的种子名。"""
    if not resolve_destination_key(destination):
        return merged
    seeds = [str(s).strip() for s in policy.seed_poi_names if str(s).strip()]
    if not seeds:
        return merged

    missing = [seed for seed in seeds if not _seed_represented(seed, merged)]
    if not missing:
        return merged
    if len(merged) >= max(12, min(18, len(seeds) + 4)) and len(missing) <= max(2, len(seeds) // 3):
        return merged

    city_ref = str(scope.get("adcode", "")).strip() or str(scope.get("city", "")).strip() or destination
    seen = {
        str(row.get("id", "")).strip() or str(row.get("name", "")).strip()
        for row in merged
    }
    augmented = list(merged)

    seed_cap = min(len(missing), max(3, min(6, len(seeds) // 2 + 1)))
    for seed in missing[:seed_cap]:
        try:
            response = amap.text_search(
                seed,
                city=city_ref,
                types=query_types_for_text(seed),
                page=1,
                offset=10,
                children=True,
                extensions="all",
            )
        except Exception:
            continue
        rows = response.get("pois", []) if isinstance(response, dict) else []
        for order, row in enumerate(rows if isinstance(rows, list) else []):
            if not isinstance(row, dict):
                continue
            poi_id = str(row.get("id", "")).strip() or str(row.get("name", "")).strip()
            if not poi_id or poi_id in seen:
                continue
            current = dict(row)
            current["_query"] = seed
            current["_query_index"] = 0
            current["_query_order"] = order
            current["_knowledge_seed"] = True
            augmented.append(current)
            seen.add(poi_id)
            break

    return augmented
