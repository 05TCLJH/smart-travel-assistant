"""诊断任意目的地 POI 检索与 guard（用法: python scripts/diagnose_destination_plan.py 伊犁）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.knowledge.destination_catalog import _load_catalog, resolve_geocode_query
from backend.planning.poi_retrieval import PoiRetrievalPipeline
from backend.planning.search_strategy import build_search_strategy, enrich_scope_with_strategy
from backend.services.persona_service import PersonaService
from backend.tools.amap_tools import TravelResearchTools
from backend.tools.grounding_tools import guard_candidate_pois, evaluate_candidate_match
from backend.tools.planning_tools import build_plan, rank_candidates


def main() -> None:
    _load_catalog.cache_clear()
    destination = sys.argv[1] if len(sys.argv) > 1 else "伊犁"
    trip = {"destination": destination, "days": 3, "budget": 3000, "start_date": "2026-06-01"}
    persona = PersonaService().enrich({"travel_style": "经典热门", "stamina": "中等", "budget_style": "舒适"}, trip)
    tools = TravelResearchTools()

    print("=== Persona / Strategy ===")
    print("style_key:", persona.get("style_key"))
    print("destination_region_type:", persona.get("destination_region_type"))
    print("hotspots:", persona.get("destination_hotspots", [])[:8])

    if not (tools.mcp_enabled and tools.amap.enabled):
        print("AMAP disabled — fallback only")
        map_data = tools.build_map_data(destination, persona)
    else:
        geocode_query = resolve_geocode_query(destination)
        print("\n=== Geocode ===")
        print("geocode_query:", geocode_query)
        geo = tools.amap.geocode(geocode_query)
        scope = tools._extract_destination_scope(geo, destination)
        strategy = build_search_strategy(destination, persona.get("travel_style", ""), scope, likes=persona.get("likes"))
        scope = enrich_scope_with_strategy(scope, strategy)
        print("scope keys:", {k: scope.get(k) for k in ("resolved_name", "province", "city", "is_scenic_region", "search_radius_km", "destination_aliases") if k in scope})
        pipeline = PoiRetrievalPipeline(tools)
        queries, policy = pipeline.build_queries(destination, persona, "", scope, strategy)
        print("policy is_wide_area:", policy.is_wide_area, "radius:", policy.search_radius_km)
        print("first queries:", queries[:10])
        rows = pipeline.collect_rows(destination, scope, queries[:12], policy)
        print("raw rows:", len(rows))
        location = tools._extract_geocode_location(geo)
        pois = pipeline.normalize(rows, location, destination, persona, scope, strategy)
        map_data = {"pois": pois, "is_fallback": False}

    raw_pois = list(map_data.get("pois") or [])
    print("\n=== After normalize ===")
    print("poi count:", len(raw_pois))
    for p in raw_pois[:10]:
        print(f"  - {p.get('name')} | {p.get('province')}/{p.get('city')} | dist={p.get('distance_to_destination_km')}km seed={p.get('knowledge_seed')}")

    weather = tools.build_weather(destination, tools.build_dates(trip["start_date"], trip["days"]))
    passed, guard = guard_candidate_pois(raw_pois, trip, persona, weather)
    print("\n=== Guard ===")
    print("passed:", len(passed), "dropped:", guard.get("dropped_count"))
    for p in (raw_pois[:5] if raw_pois else []):
        audit = evaluate_candidate_match(p, trip, persona, weather)
        print(f"  audit {p.get('name')}: is_match={audit['is_match']} hard_block={audit.get('hard_block')} warnings={audit.get('warnings')}")

    if guard.get("top_dropped"):
        print("top_dropped:", json.dumps(guard["top_dropped"][:5], ensure_ascii=False, indent=2))

    plan = build_plan(trip, persona, weather, passed or raw_pois, lambda _d: {"status": "skipped"})
    print("\n=== Plan ===")
    for day in plan.get("itinerary", []):
        print(f"  Day {day.get('day')}: {day.get('theme')} points={day.get('route_points')}")


if __name__ == "__main__":
    main()
