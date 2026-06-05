"""单日容量：负荷为主、景点数由负荷推导。"""

from __future__ import annotations

import unittest

from backend.planning.activity_load import LOAD_LIGHT, default_daily_load_budget
from backend.planning.day_capacity import derive_max_pois_cap, resolve_day_capacity
from backend.tools.routing_policy import merge_routing_policy


class DayCapacityTests(unittest.TestCase):
    def test_derive_cap_scales_with_load(self) -> None:
        weak = default_daily_load_budget("轻松", "relaxed")
        strong = default_daily_load_budget("充沛", "tight")
        self.assertLess(
            derive_max_pois_cap(weak, 2, 4),
            derive_max_pois_cap(strong, 3, 6),
        )

    def test_derive_uses_light_load_unit(self) -> None:
        self.assertEqual(derive_max_pois_cap(118, 3, 6), min(6, max(3, 118 // LOAD_LIGHT)))

    def test_resolve_explicit_max_only_lowers_cap(self) -> None:
        cap = resolve_day_capacity({"stamina": "充沛"}, {"day_pacing": "tight"})
        lowered = resolve_day_capacity(
            {"stamina": "轻松", "poi_cap_override": True, "max_pois_per_day": 2},
            {"day_pacing": "relaxed"},
            explicit_max_pois=2,
        )
        self.assertLessEqual(lowered.max_pois_cap, cap.max_pois_cap)
        self.assertEqual(lowered.max_pois_cap, 2)

    def test_merge_policy_max_follows_load_not_stamina_floor(self) -> None:
        persona = {"stamina": "充沛", "transport_preference": "打车", "poi_cap_override": True}
        trip = {"days": 3, "budget": 3000}
        merged = merge_routing_policy({"day_pacing": "relaxed", "max_pois_per_day": 6}, persona, trip)
        expected_cap = derive_max_pois_cap(merged["daily_activity_load_budget"], 3, 6)
        self.assertEqual(merged["max_pois_per_day"], expected_cap)
        self.assertLessEqual(merged["max_pois_per_day"], 6)
        self.assertGreaterEqual(merged["daily_activity_load_budget"], 90)


if __name__ == "__main__":
    unittest.main()
