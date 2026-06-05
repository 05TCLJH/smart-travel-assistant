"""单日景点顺路优化测试。"""

from __future__ import annotations

import unittest

from backend.planning.itinerary_builder import _optimize_day_poi_order
from backend.planning.venue_schedule_policy import prepare_day_pois


class ItineraryBuilderRouteOrderTests(unittest.TestCase):
    def test_optimize_day_poi_order_reduces_obvious_backtracking(self) -> None:
        day_pois = [
            {"name": "西岸入口", "type": "风景名胜", "location": "115.860,28.680"},
            {"name": "东岸栈道", "type": "风景名胜", "location": "115.940,28.680"},
            {"name": "湖心观景台", "type": "风景名胜", "location": "115.900,28.680"},
        ]

        ordered = _optimize_day_poi_order(prepare_day_pois(day_pois))

        self.assertEqual([poi["name"] for poi in ordered], ["西岸入口", "湖心观景台", "东岸栈道"])

    def test_optimize_day_poi_order_preserves_semantic_anchors(self) -> None:
        day_pois = [
            {"name": "故宫博物院", "type": "博物馆", "location": "116.397,39.916"},
            {"name": "什刹海风景区", "type": "风景名胜", "location": "116.386,39.943"},
            {"name": "中山公园", "type": "公园", "location": "116.397,39.914"},
            {"name": "景山公园", "type": "公园", "location": "116.403,39.924"},
        ]

        ordered = _optimize_day_poi_order(prepare_day_pois(day_pois))
        names = [poi["name"] for poi in ordered]

        self.assertEqual(names[0], "故宫博物院")
        self.assertEqual(names[-1], "景山公园")


if __name__ == "__main__":
    unittest.main()
