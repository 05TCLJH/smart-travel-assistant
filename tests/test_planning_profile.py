"""统一规划画像测试：验证 1-7 天都走同一套连续推导模型。"""

from __future__ import annotations

import unittest

from backend.planning.planning_profile import resolve_planning_profile


class PlanningProfileTests(unittest.TestCase):
    def test_profile_grows_smoothly_from_day_1_to_day_7(self) -> None:
        profiles = [
            resolve_planning_profile({"trip_days": day, "travel_style": "经典热门"}, days=day, max_per_day=4)
            for day in range(1, 8)
        ]

        self.assertEqual([profile.days for profile in profiles], list(range(1, 8)))
        self.assertTrue(all(profiles[index].duration_ratio <= profiles[index + 1].duration_ratio for index in range(6)))
        self.assertTrue(all(profiles[index].target_slots < profiles[index + 1].target_slots for index in range(6)))
        self.assertTrue(
            all(profiles[index].candidate_floor <= profiles[index + 1].candidate_floor for index in range(6))
        )
        self.assertTrue(
            all(profiles[index].candidate_guardrail <= profiles[index + 1].candidate_guardrail for index in range(6))
        )
        self.assertTrue(
            all(
                profiles[index].candidate_expansion_threshold
                <= profiles[index + 1].candidate_expansion_threshold
                for index in range(6)
            )
        )
        self.assertTrue(all(profiles[index].query_budget <= profiles[index + 1].query_budget for index in range(6)))
        self.assertTrue(
            all(profiles[index].enrichment_limit <= profiles[index + 1].enrichment_limit for index in range(6))
        )

    def test_wide_area_profile_keeps_more_retrieval_headroom(self) -> None:
        city_profile = resolve_planning_profile({"trip_days": 5}, days=5, max_per_day=4, is_wide_area=False, seed_count=4)
        wide_profile = resolve_planning_profile({"trip_days": 5}, days=5, max_per_day=4, is_wide_area=True, seed_count=4)

        self.assertGreaterEqual(wide_profile.query_budget, city_profile.query_budget)
        self.assertGreater(wide_profile.enrichment_limit, city_profile.enrichment_limit)
        self.assertGreaterEqual(wide_profile.supplement_affinity_floor, city_profile.supplement_affinity_floor)

    def test_strict_style_profile_raises_supplement_floor_without_breaking_continuity(self) -> None:
        relaxed = resolve_planning_profile({"trip_days": 4, "mainstream_preference": 0.8}, days=4)
        strict = resolve_planning_profile({"trip_days": 4, "mainstream_preference": 0.2, "route_style": "deep"}, days=4)

        self.assertGreater(strict.supplement_affinity_floor, relaxed.supplement_affinity_floor)
        self.assertEqual(strict.target_slots, relaxed.target_slots)


if __name__ == "__main__":
    unittest.main()
