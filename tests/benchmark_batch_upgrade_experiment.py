"""批量升级实验脚本测试支撑。

用于对比候选收集策略在真实行程生成链路中的覆盖率、耗时与搜索调用次数。
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.diagnostics.trip_benchmark import DEFAULT_BENCHMARK_CASES, TimelineRecorder, summarize_segments
from backend.mcp.amap_client import AmapMcpClient
from backend.planning.poi_retrieval.collector import diversify_collected_rows
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.planning.poi_retrieval.priority import destination_priority_score
from backend.planning.poi_retrieval.priority import raw_row_priority
from backend.planning.poi_retrieval.query_builder import query_types_for_text
from backend.planning.poi_retrieval.scope import matches_scope_text
from backend.planning.poi_retrieval.seed_coverage import ensure_catalog_seed_rows
from backend.planning.poi_retrieval.collector import select_rows_for_enrichment
from backend.planning.poi_retrieval.pipeline import PoiRetrievalPipeline
from backend.services.travel_service import TravelService
from backend.tools.grounding_tools import is_auxiliary_poi, is_secondary_poi


REPORT_DIR = Path(__file__).resolve().parent / "reports"


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


def _query_yield_count(query: str, rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if str(row.get("_query", "")).strip() == query)


def _coverage_metrics(rows: list[dict[str, Any]], policy: PoiRetrievalPolicy, queries: list[str]) -> dict[str, Any]:
    seeds = [str(seed).strip() for seed in policy.seed_poi_names if str(seed).strip()]
    represented = [seed for seed in seeds if _seed_represented(seed, rows)]
    query_hits = [query for query in queries if _query_yield_count(query, rows) > 0]
    exact_hits = [query for query in queries if policy.is_exact_query(query) and _query_yield_count(query, rows) > 0]
    return {
        "row_count": len(rows),
        "seed_coverage_count": len(represented),
        "query_hit_count": len(query_hits),
        "exact_hit_count": len(exact_hits),
        "represented_seeds": represented,
    }


def _coverage_ok(rows: list[dict[str, Any]], policy: PoiRetrievalPolicy, queries: list[str]) -> bool:
    metrics = _coverage_metrics(rows, policy, queries)
    min_rows = 16 if policy.is_wide_area else 10
    min_seed_hits = min(len(policy.seed_name_set()), 6 if policy.is_wide_area else 3)
    min_query_hits = min(len(queries), 6 if policy.is_wide_area else 4)
    return (
        metrics["row_count"] >= min_rows
        and metrics["seed_coverage_count"] >= min_seed_hits
        and metrics["query_hit_count"] >= min_query_hits
    )


def _critical_queries_for_cityless(rows: list[dict[str, Any]], policy: PoiRetrievalPolicy, queries: list[str]) -> list[str]:
    critical: list[str] = []
    seen: set[str] = set()
    seeds = policy.seed_name_set()

    def add(query: str) -> None:
        text = str(query or "").strip()
        if text and text not in seen:
            seen.add(text)
            critical.append(text)

    # 仍未覆盖的精确种子优先补救。
    for query in queries:
        if policy.is_exact_query(query) and _query_yield_count(query, rows) == 0:
            add(query)

    # 若语义化或宽范围城市查询也失败，则选几条去掉城市限制后重试。
    broad_queries = [query for query in queries if not policy.is_exact_query(query)]
    for query in broad_queries:
        if _query_yield_count(query, rows) == 0:
            add(query)
        if len(critical) >= 4:
            break

    # 兜底：若仍不足，再补试尚未被精确覆盖的种子变体。
    if len(critical) < 4:
        for seed in seeds:
            if not _seed_represented(seed, rows):
                add(seed)
            if len(critical) >= 4:
                break

    return critical


def _accept_row(
    row: dict[str, Any],
    *,
    scope: dict[str, Any],
    policy: PoiRetrievalPolicy,
    is_exact_seed: bool,
    query: str,
    query_index: int,
    order: int,
) -> dict[str, Any] | None:
    current = dict(row)
    if policy.is_wide_area and not is_exact_seed and not matches_scope_text(
        scope,
        current.get("pname", ""),
        current.get("cityname", ""),
        current.get("adname", ""),
        current.get("address", ""),
    ):
        return None
    current["_query"] = query
    current["_query_index"] = query_index
    current["_query_order"] = order
    if is_exact_seed:
        current["_knowledge_seed"] = True
    if str(current.get("parent", "") or current.get("parentid", "")).strip():
        return None
    if is_auxiliary_poi(current) or (is_secondary_poi(current) and not is_exact_seed):
        return None
    return current


def experimental_collect_rows(
    self: PoiRetrievalPipeline,
    destination: str,
    persona: dict[str, Any],
    scope: dict[str, Any],
    queries: list[str],
    policy: PoiRetrievalPolicy,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    city_ref = str(scope.get("adcode", "")).strip() or str(scope.get("city", "")).strip() or destination

    def search_once(query: str, city_arg: str, query_index: int) -> None:
        is_exact_seed = policy.is_exact_query(query)
        response = self._tools.amap.text_search(
            query,
            city=city_arg,
            types=query_types_for_text(query),
            page=1,
            offset=20,
            children=True,
            extensions="all",
        )
        rows = response.get("pois", []) if isinstance(response, dict) else []
        for order, row in enumerate(rows if isinstance(rows, list) else []):
            if not isinstance(row, dict):
                continue
            accepted = _accept_row(
                row,
                scope=scope,
                policy=policy,
                is_exact_seed=is_exact_seed,
                query=query,
                query_index=query_index,
                order=order,
            )
            if not accepted:
                continue
            poi_id = str(accepted.get("id", "")).strip() or str(accepted.get("name", "")).strip()
            if not poi_id or poi_id in seen_ids:
                continue
            seen_ids.add(poi_id)
            merged.append(accepted)

    # 第一轮：仅保留城市范围限制，按整批查询执行城市内检索。
    for query_index, query in enumerate(queries):
        city_arg = "" if policy.is_wide_area else city_ref
        search_once(query, city_arg, query_index)
        if _coverage_ok(merged, policy, queries):
            break

    # 第二轮：整批策略升级，仅对关键查询做去城市限制重试。
    if not policy.is_wide_area and not _coverage_ok(merged, policy, queries):
        critical_queries = _critical_queries_for_cityless(merged, policy, queries)
        for retry_index, query in enumerate(critical_queries, start=len(queries)):
            search_once(query, "", retry_index)
            if _coverage_ok(merged, policy, queries):
                break

    ranked = sorted(
        merged,
        key=lambda item: raw_row_priority(
            policy,
            item,
            destination_priority_fn=lambda poi: destination_priority_score(policy, poi),
        ),
    )
    diversified = diversify_collected_rows(ranked, policy)
    diversified = ensure_catalog_seed_rows(diversified, self._tools.amap, destination, scope, policy)
    base_limit = 28 if policy.is_wide_area else 18
    seed_count = len(policy.seed_name_set())
    coverage_limit = seed_count + min(10, seed_count)
    enrich_limit = max(base_limit, min(36 if policy.is_wide_area else 24, coverage_limit))
    selected = select_rows_for_enrichment(diversified, policy, max_total=enrich_limit)
    return self._tools._enrich_search_rows(selected, destination, max_rows=enrich_limit)


@contextmanager
def patched_collect_rows():
    original = PoiRetrievalPipeline.collect_rows
    PoiRetrievalPipeline.collect_rows = experimental_collect_rows  # type: ignore[assignment]
    try:
        yield
    finally:
        PoiRetrievalPipeline.collect_rows = original  # type: ignore[assignment]


@contextmanager
def count_text_search_calls() -> Any:
    original = AmapMcpClient.text_search
    counter = {"count": 0}

    def wrapped(self: AmapMcpClient, *args: Any, **kwargs: Any) -> dict[str, Any]:
        counter["count"] += 1
        return original(self, *args, **kwargs)

    AmapMcpClient.text_search = wrapped  # type: ignore[assignment]
    try:
        yield counter
    finally:
        AmapMcpClient.text_search = original  # type: ignore[assignment]


def run_case(case: dict[str, Any], *, experimental: bool) -> dict[str, Any]:
    recorder = TimelineRecorder()
    service = TravelService()
    service.research_tools.reset_amap_connection()

    def on_progress(event: dict[str, Any]) -> None:
        recorder.observe(event)

    started = perf_counter()
    context = patched_collect_rows() if experimental else nullcontext()
    with context, count_text_search_calls() as counter:
        result = service.generate(
            deepcopy(case["trip_request"]),
            deepcopy(case["persona"]),
            progress=on_progress,
        )
    elapsed = round(perf_counter() - started, 4)
    recorder.finalize()
    summary = summarize_segments(recorder.segments)
    poi_search = ((summary.get("by_step") or {}).get("research.poi_search") or {}).get("total_duration_s")
    return {
        "mode": "experimental" if experimental else "baseline",
        "elapsed_s": elapsed,
        "poi_search_s": poi_search,
        "text_search_calls": counter["count"],
        "candidate_count": (result.get("plan") or {}).get("candidate_count"),
        "planning_attempts": result.get("planning_attempts"),
        "issues": (result.get("reflection") or {}).get("issues", []),
        "day_routes": [day.get("route_points", []) for day in ((result.get("plan") or {}).get("itinerary") or [])],
    }


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    case_names = {"qingdao_cultural_3d", "beijing_classic_4d"}
    cases = [case for case in DEFAULT_BENCHMARK_CASES if case.get("name") in case_names]
    report: dict[str, Any] = {"cases": []}

    for case in cases:
        baseline = run_case(case, experimental=False)
        experimental = run_case(case, experimental=True)
        improvement = {
            "elapsed_delta_s": round(baseline["elapsed_s"] - experimental["elapsed_s"], 4),
            "poi_search_delta_s": round(float(baseline.get("poi_search_s") or 0.0) - float(experimental.get("poi_search_s") or 0.0), 4),
            "text_search_call_delta": int(baseline["text_search_calls"]) - int(experimental["text_search_calls"]),
        }
        report["cases"].append(
            {
                "name": case["name"],
                "trip_request": case["trip_request"],
                "persona": case["persona"],
                "baseline": baseline,
                "experimental": experimental,
                "improvement": improvement,
            }
        )

    output = REPORT_DIR / "batch_upgrade_experiment_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report_saved: {output}")


if __name__ == "__main__":
    main()
