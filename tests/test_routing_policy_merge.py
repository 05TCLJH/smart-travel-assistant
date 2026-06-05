"""路由策略合并测试：以负荷预算为主，点位上限由负荷推导。"""

from __future__ import annotations

import unittest

from backend.planning.day_capacity import derive_max_pois_cap
from backend.tools.routing_policy import merge_routing_policy


class RoutingPolicyMergeTests(unittest.TestCase):
    def test_relaxed_strong_stamina_keeps_load_and_derived_cap(self) -> None:
        persona = {"stamina": "强", "transport_preference": "打车"}
        trip = {"days": 3, "budget": 3000}
        merged = merge_routing_policy({"day_pacing": "relaxed", "max_pois_per_day": 6}, persona, trip)
        self.assertGreaterEqual(merged["daily_activity_load_budget"], 90)
        self.assertEqual(merged["max_pois_per_day"], derive_max_pois_cap(merged["daily_activity_load_budget"]))


if __name__ == "__main__":
    unittest.main()
