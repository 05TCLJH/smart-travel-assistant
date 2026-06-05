"""城市目的地加户外探险：近郊景点不应被默认三十五公里半径误杀。"""

from __future__ import annotations

import unittest

from backend.knowledge.destination_catalog import curated_priority_rules
from backend.planning.search_strategy import build_search_strategy
from backend.services.persona_service import PersonaService


class PoiAdventureCityTests(unittest.TestCase):
    def test_wuhan_adventure_radius_expanded(self) -> None:
        strategy = build_search_strategy("武汉", "户外探险")
        self.assertGreaterEqual(strategy.search_radius_km, 90.0)
        self.assertIn("森林公园", " ".join(strategy.query_suffixes))

    def test_wuhan_adventure_priority_rules_use_adventure_bucket(self) -> None:
        rules = curated_priority_rules("武汉", "adventure")
        niche = rules.get("niche", [])
        self.assertTrue(any("木兰" in name for name in niche))

    def test_adventure_map_not_empty_with_enrich(self) -> None:
        from dotenv import load_dotenv
        from pathlib import Path

        from backend.core.paths import PROJECT_ROOT
        from backend.tools.amap_tools import TravelResearchTools

        load_dotenv(PROJECT_ROOT / ".env")
        persona = PersonaService().enrich({}, {"destination": "武汉", "days": 3, "budget": 5000})
        tools = TravelResearchTools()
        if not tools.amap.enabled:
            self.skipTest("Amap MCP not configured")
        md = tools.build_map_data("武汉", persona, query_hint="")
        if md.get("is_fallback"):
            self.skipTest(md.get("warning", "fallback"))
        self.assertGreaterEqual(len(md.get("pois") or []), 3)


if __name__ == "__main__":
    unittest.main()
