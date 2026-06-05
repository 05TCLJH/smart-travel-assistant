"""诊断川西行程空白天（尽量少调高德：仅 1 次 geocode + 限量 POI 检索）。"""
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
from backend.tools.grounding_tools import guard_candidate_pois
from backend.tools.planning_tools import build_plan, rank_candidates


def main() -> None:
    _load_catalog.cache_clear()
    destination = "川西"
    trip = {"destination": destination, "days": 3, "budget": 3000, "start_date": "2026-06-01"}
    persona = PersonaService().enrich({"travel_style": "经典热门", "stamina": "中等", "budget_style": "舒适"}, trip)
    tools = TravelResearchTools()

    print("=== Persona / Strategy ===")
    print("style_key:", persona.get("style_key"))
    print("destination_region_type:", persona.get("destination_region_type"))
    print("hotspots:", persona.get("destination_hotspots", [])[:5], "...")

    if not (tools.mcp_enabled and tools.amap.enabled):
        print("AMAP disabled — using fallback path only")
        map_data = tools.build_map_data(destination, persona)
    else:
        print("\n=== Geocode + limited search ===")
        geocode_query = resolve_geocode_query(destination)
        print("geocode_query:", geocode_query)
        geo = tools.amap.geocode(geocode_query)
        scope = tools._extract_destination_scope(geo, destination)
        strategy = build_search_strategy(destination, persona.get("travel_style", ""), scope, likes=persona.get("likes"))
        scope = enrich_scope_with_strategy(scope, strategy)
        print("scope:", {k: scope.get(k) for k in ("resolved_name", "province", "city", "is_scenic_region", "destination_aliases") if k in scope})
        pipeline = PoiRetrievalPipeline(tools)
        queries, policy = pipeline.build_queries(destination, persona, "", scope, strategy)
        queries = queries[:8]
        print("first queries:", queries)
        rows = pipeline.collect_rows(destination, scope, queries, policy)
        print("raw rows from limited queries:", len(rows))
        location = tools._extract_geocode_location(geo)
        pois = pipeline.normalize(rows, location, destination, persona, scope, strategy)
        map_data = {
            "pois": pois,
            "is_fallback": False,
            "search_query": " | ".join(queries),
        }

    raw_pois = list(map_data.get("pois") or [])
    print("\n=== Map data ===")
    print("provider fallback:", map_data.get("is_fallback"))
    print("poi count:", len(raw_pois))
    for p in raw_pois[:8]:
        print(f"  - {p.get('name')} | {p.get('province')}/{p.get('city')} | dist={p.get('distance_to_destination_km')}km")

    weather = tools.build_weather(destination, tools.build_dates(trip["start_date"], trip["days"]))
    passed, guard = guard_candidate_pois(raw_pois, trip, persona, weather)
    print("\n=== Guard ===")
    print("passed:", len(passed), "dropped:", guard.get("dropped_count", len(raw_pois) - len(passed)))
    if guard.get("drop_samples"):
        print("drop samples:", json.dumps(guard["drop_samples"][:3], ensure_ascii=False, indent=2))

    ranked = rank_candidates(passed or raw_pois, persona, weather)
    print("\n=== Rank (top 5) ===")
    for p in ranked[:5]:
        print(
            f"  {p.get('name')} suit={p.get('suitability_score')} "
            f"pref_hit={p.get('preference_hit')} constraint={p.get('constraint_score')}"
        )

    def dummy_route(day_pois):
        return {"status": "skipped", "message": "diagnostic"}

    plan = build_plan(trip, persona, weather, passed or raw_pois, dummy_route)
    print("\n=== Plan ===")
    print("candidate_count:", plan.get("candidate_count"))
    for day in plan.get("itinerary", []):
        print(f"  Day {day.get('day')}: {day.get('theme')} points={day.get('route_points')}")


if __name__ == "__main__":
    main()
