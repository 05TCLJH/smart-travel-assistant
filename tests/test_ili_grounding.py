"""伊犁环线：跨州府核心景点不得被守卫规则误杀。"""

from __future__ import annotations

import unittest

from backend.knowledge.destination_catalog import _load_catalog
from backend.planning.destination_constraints import resolve_constraint_profile
from backend.services.persona_service import PersonaService
from backend.tools.grounding_tools import destination_conflict, guard_candidate_pois


class IliGroundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _load_catalog.cache_clear()

    def test_sayram_in_bortala_not_conflict(self) -> None:
        poi = {
            "name": "赛里木湖国家级风景名胜区",
            "city": "博尔塔拉蒙古自治州",
            "province": "",
            "address": "博尔塔拉蒙古自治州博乐市",
            "distance_to_destination_km": 78.0,
            "knowledge_seed": True,
        }
        persona = PersonaService().enrich(
            {"travel_style": "经典热门"},
            {"destination": "伊犁", "days": 3, "budget": 3000},
        )
        profile = resolve_constraint_profile("伊犁", persona)
        self.assertTrue(profile.poi_in_scope(poi))
        self.assertFalse(destination_conflict(poi, "伊犁", persona))

    def test_guard_keeps_sayram_candidates(self) -> None:
        trip = {"destination": "伊犁", "days": 3, "budget": 3000}
        persona = PersonaService().enrich({"travel_style": "经典热门"}, trip)
        pois = [
            {
                "name": "赛里木湖国家级风景名胜区",
                "city": "博尔塔拉蒙古自治州",
                "province": "",
                "address": "博尔塔拉",
                "distance_to_destination_km": 78.0,
                "knowledge_seed": True,
                "knowledge_tags": ["nature"],
                "type": "风景名胜",
                "ticket": "70",
            },
            {
                "name": "那拉提旅游风景区",
                "city": "伊犁哈萨克自治州",
                "province": "新疆维吾尔自治区",
                "address": "新源县",
                "distance_to_destination_km": 120.0,
                "knowledge_seed": True,
                "knowledge_tags": ["nature"],
                "type": "风景名胜",
                "ticket": "95",
            },
        ]
        passed, guard = guard_candidate_pois(pois, trip, persona, {"rating": "良好"})
        self.assertGreaterEqual(len(passed), 2, guard)
        self.assertGreaterEqual(guard.get("kept_count", 0), 2)


if __name__ == "__main__":
    unittest.main()
