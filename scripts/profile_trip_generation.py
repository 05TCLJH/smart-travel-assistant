"""详细计时分析脚本：对行程方案生成的每个模块进行计时，定位瓶颈。"""

from __future__ import annotations

import json
import sys
import time
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# ============================================================
# 计时基础设施
# ============================================================

_timings: list[dict] = []
_timing_stack: list[tuple[str, float]] = []
_timing_lock = threading.Lock()


def _now() -> float:
    return time.perf_counter()


def push_timing(label: str) -> None:
    with _timing_lock:
        _timing_stack.append((label, _now()))


def pop_timing() -> None:
    with _timing_lock:
        if _timing_stack:
            label, start = _timing_stack.pop()
            _timings.append({"label": label, "elapsed_s": round(_now() - start, 4)})


def reset_timings() -> None:
    with _timing_lock:
        _timings.clear()
        _timing_stack.clear()


def get_timings() -> list[dict]:
    with _timing_lock:
        return list(_timings)


def _wrap_fn(original, label: str):
    """返回一个包装后的函数，调用前后自动计时。"""
    def wrapper(*args, **kwargs):
        push_timing(label)
        try:
            return original(*args, **kwargs)
        finally:
            pop_timing()
    return wrapper


def _wrap_method(owner, method_name: str, label: str):
    """替换对象上的方法，加入计时。"""
    original = getattr(owner, method_name, None)
    if original is None:
        return
    setattr(owner, method_name, _wrap_fn(original, label))


# ============================================================
# 注入计时点
# ============================================================

def inject_timing_hooks(service):
    """在 TravelService 和 TravelResearchTools 的关键方法上注入计时。"""
    tools = service.research_tools

    # --- TravelResearchTools 关键方法 ---
    _wrap_method(tools, "build_weather", "research.build_weather")
    _wrap_method(tools, "build_map_data", "research.build_map_data")
    _wrap_method(tools, "search_candidate_pois", "research.search_candidate_pois")
    _wrap_method(tools, "resolve_geocode_payload", "amap.geocode")
    _wrap_method(tools, "_enrich_search_rows", "research.enrich_search_rows")

    # --- AmapMcpClient 关键方法 ---
    amap = tools.amap
    _wrap_method(amap, "text_search", "amap.text_search")
    _wrap_method(amap, "search_detail", "amap.search_detail")
    _wrap_method(amap, "weather", "amap.weather")
    _wrap_method(amap, "geocode", "amap.geocode_raw")
    _wrap_method(amap, "regeocode", "amap.regeocode")

    # --- 注入 PoiRetrievalPipeline ---
    pipeline = tools._poi_pipeline
    _wrap_method(pipeline, "run", "pipeline.run")
    _wrap_method(pipeline, "build_queries", "pipeline.build_queries")
    _wrap_method(pipeline, "collect_rows", "pipeline.collect_rows")
    _wrap_method(pipeline, "normalize", "pipeline.normalize")

    # --- 注入 collect_candidate_rows ---
    from backend.planning.poi_retrieval import collector
    _wrap_method(collector, "collect_candidate_rows", "collector.collect_candidate_rows")
    _wrap_method(collector, "diversify_collected_rows", "collector.diversify")

    # --- 注入 normalize_pois ---
    from backend.planning.poi_retrieval import normalizer
    _wrap_method(normalizer, "normalize_pois", "normalizer.normalize_pois")

    # --- 注入 guard_candidate_pois ---
    from backend.tools import grounding_tools
    _wrap_method(grounding_tools, "guard_candidate_pois", "tools.guard_candidate_pois")

    # --- 注入 rank_candidates ---
    from backend.planning import candidate_scoring
    _wrap_method(candidate_scoring, "rank_candidates", "scoring.rank_candidates")

    # --- 注入 build_plan ---
    from backend.planning import itinerary_builder
    _wrap_method(itinerary_builder, "build_plan", "itinerary.build_plan")
    _wrap_method(itinerary_builder, "_optimize_day_poi_order", "itinerary.optimize_day_order")

    # --- 注入 select_diverse_candidates ---
    from backend.planning import candidate_selection
    _wrap_method(candidate_selection, "select_diverse_candidates", "selection.select_diverse")
    _wrap_method(candidate_selection, "cluster_candidates_by_district", "selection.cluster_by_district")

    # --- 注入 distribute_candidates_by_load ---
    from backend.planning import activity_load
    _wrap_method(activity_load, "distribute_candidates_by_load", "activity_load.distribute")

    # --- 注入 select_planning_pool ---
    from backend.planning import style_affinity
    _wrap_method(style_affinity, "select_planning_pool", "style_affinity.select_pool")

    # --- 注入 LLM 调用 ---
    from backend.agents import llm_utils
    _wrap_method(llm_utils, "invoke_structured_json", "llm.invoke_structured_json")
    _wrap_method(llm_utils, "invoke_brief", "llm.invoke_brief")

    # --- 注入 review_plan ---
    from backend.tools import budget_tools
    _wrap_method(budget_tools, "review_plan", "budget.review_plan")

    # --- 注入 search_local_foods ---
    from backend.tools import local_service_tools
    _wrap_method(local_service_tools, "search_local_foods", "local.search_foods")


# ============================================================
# 运行测试
# ============================================================

TEST_CASES = [
    {
        "name": "南昌文化3日",
        "trip_request": {
            "destination": "南昌",
            "start_date": "2026-06-01",
            "days": 3,
            "budget": 3000,
        },
        "persona": {
            "travel_style": "文化历史",
            "stamina": "适中",
            "transport_preference": "地铁/公交优先",
        },
    },
    {
        "name": "北京经典4日",
        "trip_request": {
            "destination": "北京",
            "start_date": "2026-06-08",
            "days": 4,
            "budget": 5200,
        },
        "persona": {
            "travel_style": "经典热门",
            "stamina": "适中",
            "transport_preference": "地铁/公交优先",
        },
    },
    {
        "name": "上海休闲3日",
        "trip_request": {
            "destination": "上海",
            "start_date": "2026-06-15",
            "days": 3,
            "budget": 4000,
        },
        "persona": {
            "travel_style": "休闲度假",
            "stamina": "轻松",
            "transport_preference": "地铁/公交优先",
        },
    },
]


def _print_timings(label: str, timings: list[dict]):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"{'模块':<50} {'耗时(s)':>10} {'占比':>8}")
    print(f"{'-'*70}")

    total = sum(t["elapsed_s"] for t in timings)
    for t in sorted(timings, key=lambda x: -x["elapsed_s"]):
        pct = (t["elapsed_s"] / total * 100) if total > 0 else 0
        print(f"{t['label']:<50} {t['elapsed_s']:>10.4f} {pct:>7.1f}%")

    # 汇总
    grouped = defaultdict(float)
    for t in timings:
        prefix = t["label"].split(".")[0]
        grouped[prefix] += t["elapsed_s"]
    print(f"\n--- 按模块汇总 ---")
    for key, val in sorted(grouped.items(), key=lambda x: -x[1]):
        pct = (val / total * 100) if total > 0 else 0
        print(f"  {key:<48} {val:>10.4f}s ({pct:.1f}%)")
    print(f"  {'总计':<48} {total:>10.4f}s")


def run_profile():
    from backend.services.travel_service import TravelService

    for case in TEST_CASES:
        name = case["name"]
        print(f"\n{'#'*70}")
        print(f"#  测试用例: {name}")
        print(f"{'#'*70}")

        reset_timings()
        service = TravelService()
        inject_timing_hooks(service)

        t0 = _now()
        try:
            result = service.generate(
                case["trip_request"],
                case["persona"],
            )
            elapsed = _now() - t0
            print(f"\n  总耗时: {elapsed:.2f}s")
            plan = result.get("plan", {})
            itinerary = plan.get("itinerary", [])
            print(f"  候选景点: {plan.get('candidate_count', 0)} 个")
            print(f"  生成天数: {len(itinerary)} 天")
            for day in itinerary:
                pts = day.get("route_points", [])
                print(f"    Day {day.get('day', '?')}: {len(pts)} 个景点 - {', '.join(pts[:5])}")
        except Exception as e:
            elapsed = _now() - t0
            print(f"\n  失败 (耗时: {elapsed:.2f}s): {e}")

        _print_timings(f"耗时明细 - {name}", get_timings())


if __name__ == "__main__":
    run_profile()