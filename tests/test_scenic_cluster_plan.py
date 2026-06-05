"""行程编排：同一景区簇不得在同一天或全程重复出现。"""

from __future__ import annotations

import unittest

from backend.planning.scenic_clusters import dedupe_by_scenic_cluster, scenic_cluster_key
from backend.services.persona_service import PersonaService
from backend.tools.planning_tools import build_plan, distribute_candidates, select_diverse_candidates


class ScenicClusterPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.persona = PersonaService().enrich(
            {"travel_style": "经典热门"},
            {"destination": "伊犁", "days": 3, "budget": 3000},
        )
        self.seeds = set(self.persona.get("destination_hotspots", []) or [])

    def test_cluster_key_merges_variants(self) -> None:
        self.assertEqual(
            scenic_cluster_key("喀拉峻大草原乌孙夏都", self.seeds),
            scenic_cluster_key("喀拉峻风景区", self.seeds),
        )
        self.assertEqual(
            scenic_cluster_key("那拉提空中草原", self.seeds),
            scenic_cluster_key("那拉提国家森林公园", self.seeds),
        )
        self.assertEqual(
            scenic_cluster_key("赛里木湖国家级风景名胜区", self.seeds),
            scenic_cluster_key("赛里木湖出口(G30连霍高速西向)", self.seeds),
        )

    def test_cluster_key_nalati_three_aliases_matches_image_cases(self) -> None:
        names = ["那拉提国家森林公园", "那拉提河谷草原森林公园", "那拉提自治区级风景名胜区"]
        keys = {scenic_cluster_key(n, self.seeds) for n in names}
        self.assertEqual(len(keys), 1, keys)

    def test_cluster_key_nalati_variants_without_seeds(self) -> None:
        """无目的地种子时，景区通名截断规则仍须把同一品牌的子点归并。"""
        self.assertEqual(
            scenic_cluster_key("那拉提空中草原", None),
            scenic_cluster_key("那拉提国家森林公园", None),
        )

    def test_dedupe_keeps_one_per_cluster(self) -> None:
        pois = [
            {"name": "喀拉峻大草原", "suitability_score": 80},
            {"name": "喀拉峻风景区", "suitability_score": 70},
            {"name": "那拉提空中草原", "suitability_score": 90},
        ]
        out = dedupe_by_scenic_cluster(pois, seed_names=self.seeds, max_per_cluster=1)
        self.assertEqual(len(out), 2)
        self.assertEqual(len(out), 2)
        self.assertTrue(any("那拉提" in p["name"] for p in out))
        self.assertTrue(any("喀拉峻" in p["name"] for p in out))

    def test_build_plan_no_duplicate_cluster_per_day(self) -> None:
        candidate_pois = [
            {"name": "喀拉峻大草原", "type": "风景名胜", "location": "81.0,43.0", "suitability_score": 88, "constraint_score": 80, "preference_hit": True, "canonical_tags": ["nature"]},
            {"name": "喀拉峻大草原乌孙夏都", "type": "风景名胜", "location": "81.1,43.1", "suitability_score": 85, "constraint_score": 78, "preference_hit": True, "canonical_tags": ["nature"]},
            {"name": "喀拉峻风景区", "type": "风景名胜", "location": "81.2,43.2", "suitability_score": 82, "constraint_score": 75, "preference_hit": True, "canonical_tags": ["nature"]},
            {"name": "那拉提空中草原", "type": "风景名胜", "location": "83.0,43.5", "suitability_score": 90, "constraint_score": 85, "preference_hit": True, "canonical_tags": ["nature"]},
            {"name": "那拉提国家森林公园", "type": "风景名胜", "location": "83.1,43.6", "suitability_score": 86, "constraint_score": 80, "preference_hit": True, "canonical_tags": ["nature"]},
            {"name": "赛里木湖国家级风景名胜区", "type": "风景名胜", "location": "81.0,44.6", "suitability_score": 92, "constraint_score": 88, "preference_hit": True, "canonical_tags": ["nature"]},
            {"name": "赛里木湖", "type": "风景名胜", "location": "81.0,44.7", "suitability_score": 88, "constraint_score": 85, "preference_hit": True, "canonical_tags": ["nature"]},
            {"name": "赛里木湖出口(G30连霍高速西向)", "type": "地名", "location": "81.0,44.8", "suitability_score": 60, "constraint_score": 70, "preference_hit": True, "canonical_tags": ["nature"]},
            {"name": "霍城薰衣草", "type": "风景名胜", "location": "80.9,44.0", "suitability_score": 75, "constraint_score": 72, "preference_hit": True, "canonical_tags": ["nature"]},
        ]
        trip = {"destination": "伊犁", "days": 3, "budget": 3000}
        plan = build_plan(trip, self.persona, {"rating": "良好"}, candidate_pois, lambda _d: {"status": "skipped"})
        for day in plan["itinerary"]:
            points = day.get("route_points", [])
            clusters = [scenic_cluster_key(name, self.seeds) for name in points]
            self.assertEqual(len(clusters), len(set(clusters)), f"duplicate cluster in day {day.get('day')}: {points}")

        all_clusters: list[str] = []
        for day in plan["itinerary"]:
            for name in day.get("route_points", []):
                all_clusters.append(scenic_cluster_key(name, self.seeds))
        self.assertEqual(len(all_clusters), len(set(all_clusters)), f"duplicate across trip: {all_clusters}")

    def test_cluster_key_kuanzhai_parenthetical_and_plaza(self) -> None:
        seeds = {"宽窄巷子"}
        cigar = {"name": "长城雪茄(宽窄巷子店)", "type": "风景名胜;特色商业街", "poi_role": "street_landmark"}
        plaza = {"name": "宽窄巷子东广场", "type": "风景名胜", "poi_role": "street_landmark"}
        self.assertEqual(
            scenic_cluster_key(cigar["name"], seeds, poi=cigar),
            scenic_cluster_key(plaza["name"], seeds, poi=plaza),
        )

    def test_distribute_skips_reused_cluster(self) -> None:
        selected = [
            {"name": "赛里木湖"},
            {"name": "赛里木湖观景台"},
            {"name": "那拉提空中草原"},
        ]
        buckets = distribute_candidates(selected, days=2, max_per_day=3, seed_names=self.seeds)
        day1 = buckets[0]
        self.assertLessEqual(len(day1), 3)
        clusters = [scenic_cluster_key(p["name"], self.seeds) for p in day1]
        self.assertEqual(len(clusters), len(set(clusters)))


if __name__ == "__main__":
    unittest.main()
