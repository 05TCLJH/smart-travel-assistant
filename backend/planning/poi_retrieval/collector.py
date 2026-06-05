"""高德景点候选行采集，仅负责搜索与粗筛，不做完整归一化。"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.planning.poi_retrieval.priority import raw_row_priority
from backend.planning.poi_retrieval.query_builder import query_types_for_text
from backend.planning.poi_retrieval.scope import has_scope_text, matches_scope_text
from backend.tools.grounding_tools import is_auxiliary_poi, is_secondary_poi


class AmapSearchClient(Protocol):
    def text_search(
        self,
        query: str,
        *,
        city: str = "",
        types: str = "",
        page: int = 1,
        offset: int = 20,
        children: bool = True,
        extensions: str = "all",
    ) -> dict[str, Any]: ...


def collect_candidate_rows(
    amap: AmapSearchClient,
    destination: str,
    scope: dict[str, Any],
    queries: list[str],
    policy: PoiRetrievalPolicy,
    *,
    priority_score_fn: Callable[[dict[str, Any]], float],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    search_errors: list[str] = []
    city_ref = str(scope.get("adcode", "")).strip() or str(scope.get("city", "")).strip() or destination
    seed_names = policy.seed_name_set()
    early_stop_total = 20 if policy.is_wide_area else 10
    early_seed_target = min(len(seed_names), 7 if policy.is_wide_area else 3)

    for query_index, query in enumerate(queries):
        is_exact_seed = policy.is_exact_query(query)
        pages = (1,) if is_exact_seed else (1,)
        attempts: list[tuple[str, tuple[int, ...]]] = []
        if policy.is_wide_area:
            if city_ref:
                attempts.append((city_ref, pages))
            if destination and destination != city_ref:
                attempts.append((destination, pages))
            attempts.append(("", pages))
        else:
            attempts.append((city_ref, pages))
            if not is_exact_seed:
                attempts.append(("", (1,)))

        for city_arg, page_set in attempts:
            for page in page_set:
                try:
                    response = amap.text_search(
                        query,
                        city=city_arg,
                        types=query_types_for_text(query),
                        page=page,
                        offset=20,
                        children=True,
                        extensions="all",
                    )
                    rows = response.get("pois", [])
                except Exception as exc:
                    search_errors.append(f"「{query}」city={city_arg or '(空)'} page={page}: {exc}")
                    break

                for order, row in enumerate(rows if isinstance(rows, list) else []):
                    if not isinstance(row, dict):
                        continue
                    current = dict(row)
                    if policy.is_wide_area and not is_exact_seed:
                        admin_parts = (
                            current.get("pname", ""),
                            current.get("cityname", ""),
                            current.get("adname", ""),
                        )
                        if has_scope_text(*admin_parts) and not matches_scope_text(scope, *admin_parts):
                            continue
                    current["_query"] = query
                    current["_query_index"] = query_index
                    current["_query_order"] = order
                    if is_exact_seed:
                        current["_knowledge_seed"] = True
                    if str(current.get("parent", "") or current.get("parentid", "")).strip():
                        continue
                    poi_name = str(current.get("name", "")).strip()
                    if is_auxiliary_poi(current) or (
                        is_secondary_poi(current) and not is_exact_seed
                    ):
                        continue
                    poi_id = str(current.get("id", "")).strip() or poi_name
                    if not poi_id or poi_id in seen:
                        continue
                    seen.add(poi_id)
                    merged.append(current)

                if len(rows) < 20:
                    break
            if len(merged) >= early_stop_total and _seed_coverage_count(seed_names, merged) >= early_seed_target:
                break
        if len(merged) >= early_stop_total and _seed_coverage_count(seed_names, merged) >= early_seed_target:
            break
        if len(merged) >= 48:
            break

    if not merged and search_errors:
        raise RuntimeError(f"高德 POI 检索失败：{search_errors[0]}")

    ranked = sorted(
        merged,
        key=lambda item: raw_row_priority(
            policy,
            item,
            destination_priority_fn=lambda poi: priority_score_fn(poi),
        ),
    )
    return diversify_collected_rows(ranked, policy)


def _seed_coverage_count(seed_names: set[str], rows: list[dict[str, Any]]) -> int:
    if not seed_names:
        return 0
    covered: set[str] = set()
    # 第一轮：先保证每个知识库热点至少留下一个代表项。
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        for seed in seed_names:
            if seed in name or (len(name) >= 4 and name in seed):
                covered.add(seed)
    return len(covered)


def diversify_collected_rows(
    rows: list[dict[str, Any]],
    policy: PoiRetrievalPolicy,
    *,
    max_total: int = 36,
    per_query_cap: int = 6,
) -> list[dict[str, Any]]:
    """按检索词轮询取样，避免单个热点查询（如解放碑）占满候选配额。"""
    if not rows:
        return []
    # 户外探险等城市目的地种子常仅 3 个，仍需按查询词轮询，避免单一大景区停车场占满配额
    skip_diversify = (
        not policy.is_wide_area
        and len(policy.seed_poi_names) < 2
        and policy.style_key not in {"adventure", "offbeat", "cultural"}
    )
    if skip_diversify:
        return rows[:max_total]

    per_cap = 6
    if policy.style_key == "adventure":
        per_cap = 5

    # 第二轮：按查询轮转补齐，尽量维持热点之间的横向覆盖。
    buckets: dict[str, list[dict[str, Any]]] = {}
    query_order: list[str] = []
    for row in rows:
        query = str(row.get("_query", "")).strip() or "__misc__"
        if query not in buckets:
            buckets[query] = []
            query_order.append(query)
        if len(buckets[query]) < per_cap:
            buckets[query].append(row)

    diversified: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    while len(diversified) < max_total:
        progressed = False
        for query in query_order:
            bucket = buckets.get(query) or []
            while bucket:
                row = bucket.pop(0)
                poi_id = str(row.get("id", "")).strip() or str(row.get("name", "")).strip()
                if poi_id and poi_id in seen_ids:
                    continue
                if poi_id:
                    seen_ids.add(poi_id)
                diversified.append(row)
                progressed = True
                if len(diversified) >= max_total:
                    break
            if len(diversified) >= max_total:
                break
        if not progressed:
            break
    return diversified


def _canonical_seed_for_query(query: str, seeds: set[str]) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    if text in seeds:
        return text
    for seed in sorted(seeds, key=len, reverse=True):
        if seed and (seed in text or text in seed):
            return seed
    return text


def select_rows_for_enrichment(
    rows: list[dict[str, Any]],
    policy: PoiRetrievalPolicy,
    *,
    max_total: int,
) -> list[dict[str, Any]]:
    """在昂贵的 detail/坐标精修前先做覆盖优先采样，避免前几个热门种子吃满预算。"""
    if not rows:
        return []
    budget = max(6, int(max_total or 18))
    seeds = policy.seed_name_set()
    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    covered_seeds: set[str] = set()

    def add_row(row: dict[str, Any]) -> bool:
        poi_id = str(row.get("id", "")).strip() or str(row.get("name", "")).strip()
        if not poi_id or poi_id in seen_ids or len(selected) >= budget:
            return False
        seen_ids.add(poi_id)
        selected.append(row)
        return True

    for row in rows:
        query = str(row.get("_query", "")).strip()
        seed = _canonical_seed_for_query(query, seeds) if row.get("_knowledge_seed") else ""
        if not seed or seed in covered_seeds:
            continue
        if add_row(row):
            covered_seeds.add(seed)
        if len(selected) >= budget:
            return selected

    buckets: dict[str, list[dict[str, Any]]] = {}
    query_order: list[str] = []
    for row in rows:
        query = str(row.get("_query", "")).strip() or "__misc__"
        if query not in buckets:
            buckets[query] = []
            query_order.append(query)
        buckets[query].append(row)

    while len(selected) < budget:
        progressed = False
        for query in query_order:
            bucket = buckets.get(query) or []
            while bucket:
                row = bucket.pop(0)
                if add_row(row):
                    progressed = True
                    break
            if len(selected) >= budget:
                break
        if not progressed:
            break

    return selected
