"""活动负荷：估算、按日分配、时间轴。"""

from __future__ import annotations

import unittest

from backend.knowledge.destination_catalog import (
    _load_catalog,
    merged_visit_profiles_for_destination,
)
from backend.planning.activity_load import (
    build_activity_timeline,
    can_assign_poi_to_day,
    distribute_candidates_by_load,
    enrich_poi_with_activity_load,
    estimate_activity_load,
)
from backend.services.persona_service import PersonaService
from backend.tools.planning_tools import build_plan


class ActivityLoadTests(unittest.TestCase):
    def test_mountain_scenic_is_full_day(self) -> None:
        poi = enrich_poi_with_activity_load(
            {"name": "武功山风景名胜区", "type": "风景名胜;国家级景点", "knowledge_tags": ["自然风景"]}
        )
        self.assertGreaterEqual(poi["activity_load"], 90)
        self.assertEqual(poi["activity_tier"], "full_day")

    def test_full_day_blocks_second_major_poi(self) -> None:
        mountain = enrich_poi_with_activity_load({"name": "峨眉山风景名胜区", "type": "风景名胜", "knowledge_tags": ["自然风景"]})
        museum = enrich_poi_with_activity_load({"name": "峨眉山博物馆", "type": "博物馆", "knowledge_tags": ["历史文化"]})
        self.assertTrue(can_assign_poi_to_day([], mountain, 118, 6))
        self.assertFalse(can_assign_poi_to_day([mountain], museum, 118, 6))

    def test_distribute_puts_heavy_poi_alone(self) -> None:
        mountain = enrich_poi_with_activity_load(
            {"name": "黄山风景区", "type": "风景名胜", "suitability_score": 90, "knowledge_tags": ["自然风景"]}
        )
        light_a = enrich_poi_with_activity_load({"name": "屯溪老街", "type": "购物", "suitability_score": 80, "knowledge_tags": ["街区"]})
        light_b = enrich_poi_with_activity_load({"name": "黎阳in巷", "type": "购物", "suitability_score": 75, "knowledge_tags": ["街区"]})
        buckets = distribute_candidates_by_load([light_a, mountain, light_b], days=2, daily_budget=118, max_per_day=4)
        mountain_day = next(i for i, b in enumerate(buckets) if any("黄山" in p["name"] for p in b))
        self.assertEqual(len(buckets[mountain_day]), 1)

    def test_backfill_prefers_preference_matched_candidates(self) -> None:
        selected = [
            enrich_poi_with_activity_load(
                {
                    "name": "江滩步道",
                    "type": "公园广场",
                    "suitability_score": 88,
                    "preference_hit": True,
                    "style_affinity": 74,
                }
            )
        ]
        low_affinity = enrich_poi_with_activity_load(
            {
                "name": "游客服务中心广场",
                "type": "生活服务",
                "suitability_score": 60,
                "preference_hit": False,
                "style_affinity": 18,
            }
        )
        matched_fill = enrich_poi_with_activity_load(
            {
                "name": "老城夜市",
                "type": "步行街",
                "suitability_score": 80,
                "preference_hit": True,
                "style_affinity": 68,
            }
        )
        buckets = distribute_candidates_by_load(
            selected,
            days=1,
            daily_budget=110,
            max_per_day=4,
            supplemental_pool=[low_affinity, matched_fill],
            min_pois_per_day=2,
            min_day_load_ratio=0.5,
            min_supplement_style_affinity=36.0,
        )
        names = [poi["name"] for poi in buckets[0]]
        self.assertIn("老城夜市", names)
        self.assertNotIn("游客服务中心广场", names)

    def test_build_plan_full_day_mountain_single_slot(self) -> None:
        persona = PersonaService().enrich({"travel_style": "经典热门", "stamina": "强"}, {"destination": "萍乡", "days": 2, "budget": 4000})
        candidates = [
            enrich_poi_with_activity_load(
                {
                    "name": "武功山风景名胜区",
                    "type": "风景名胜",
                    "location": "114.0,27.5",
                    "suitability_score": 95,
                    "constraint_score": 90,
                    "preference_hit": True,
                    "canonical_tags": ["nature"],
                }
            ),
            enrich_poi_with_activity_load(
                {
                    "name": "安源路矿工人运动纪念馆",
                    "type": "博物馆",
                    "location": "113.9,27.6",
                    "suitability_score": 82,
                    "constraint_score": 80,
                    "preference_hit": True,
                    "canonical_tags": ["museum", "history_culture"],
                }
            ),
            enrich_poi_with_activity_load(
                {
                    "name": "孽龙洞风景区",
                    "type": "风景名胜",
                    "location": "113.8,27.7",
                    "suitability_score": 78,
                    "constraint_score": 75,
                    "preference_hit": True,
                    "canonical_tags": ["nature"],
                }
            ),
        ]
        plan = build_plan(
            {"destination": "萍乡", "days": 2, "budget": 4000},
            persona,
            {"rating": "良好"},
            candidates,
            lambda _d: {"status": "skipped"},
            routing_policy={"max_pois_per_day": 5, "daily_activity_load_budget": 118, "prefer_cluster_by_area": False},
        )
        wugong_day = next((d for d in plan["itinerary"] if "武功山" in " ".join(d.get("route_points", []))), None)
        self.assertIsNotNone(wugong_day)
        self.assertEqual(len(wugong_day.get("route_points", [])), 1)
        self.assertIn("整日", wugong_day.get("day_note", "") or wugong_day.get("day_intensity", ""))

    def test_timeline_full_day_starts_early(self) -> None:
        poi = enrich_poi_with_activity_load({"name": "华山风景名胜区", "type": "风景名胜"})
        timeline = build_activity_timeline([poi])
        self.assertTrue(any("08:" in item["time"] for item in timeline))
        self.assertTrue(any("全天" in item["activity"] for item in timeline))

    def test_theme_park_is_half_day(self) -> None:
        poi = enrich_poi_with_activity_load({"name": "上海迪士尼度假区", "type": "体育休闲"})
        self.assertEqual(poi["venue_archetype"], "theme_park")
        self.assertAlmostEqual(poi["visit_hours"], 6.0, places=1)
        self.assertEqual(poi["schedule_mode"], "theme_park")
        self.assertGreaterEqual(poi["activity_load"], 68)
        self.assertLess(poi["activity_load"], 95)

    def test_auxiliary_entrance_is_light(self) -> None:
        poi = enrich_poi_with_activity_load({"name": "黄山风景区南大门售票处", "type": "生活服务"})
        self.assertLessEqual(poi["activity_load"], 25)

    def test_provincial_museum_is_half_day_load_but_hours_capped(self) -> None:
        poi = enrich_poi_with_activity_load({"name": "江西省博物馆", "type": "博物馆"})
        self.assertGreaterEqual(poi["activity_load"], 68)
        self.assertLessEqual(poi["visit_hours"], 3.5)
        self.assertEqual(poi.get("schedule_mode"), "contiguous_gate")

    def test_knowledge_profile_overrides_rules(self) -> None:
        _load_catalog.cache_clear()
        profiles = merged_visit_profiles_for_destination("成都")
        self.assertIn("大熊猫繁育研究基地", profiles)
        poi = enrich_poi_with_activity_load(
            {"name": "成都大熊猫繁育研究基地", "type": "风景名胜"},
            destination="成都",
            visit_profiles=profiles,
        )
        self.assertEqual(poi["activity_load_source"], "knowledge")
        self.assertAlmostEqual(poi["visit_hours"], 3.5, places=1)
        self.assertEqual(poi["activity_tier"], "extended")

    def test_enrich_is_idempotent(self) -> None:
        base = enrich_poi_with_activity_load({"name": "人民公园", "type": "公园"})
        again = enrich_poi_with_activity_load(base)
        self.assertEqual(base["activity_load"], again["activity_load"])
        self.assertEqual(base["activity_load_source"], again["activity_load_source"])

    def test_typecode_scenic_boost(self) -> None:
        poi = estimate_activity_load(
            {"name": "云台山", "type": "风景名胜", "typecode": "110202"}
        )
        self.assertGreaterEqual(poi["activity_load"], 50)


if __name__ == "__main__":
    unittest.main()
