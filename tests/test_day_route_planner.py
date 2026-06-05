"""单日路线规划器：缺少道路轨迹时不输出直线折线。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.planning.route_geometry.service import DayRoutePlanner, resolve_effective_mode
from backend.tools.amap_tools import TravelResearchTools, _AmapRouteAdapter


class ResolveEffectiveModeTests(unittest.TestCase):
    def test_long_segment_upgrades_walking_to_driving(self) -> None:
        tools = TravelResearchTools()
        coords = ["81.0,43.0", "84.0,43.5"]
        mode = resolve_effective_mode(
            "walking",
            coords,
            distance_km_fn=tools.distance_km,
            parse_lnglat_fn=tools.parse_lnglat,
        )
        self.assertEqual(mode, "driving")


class DayRoutePlannerTests(unittest.TestCase):
    def test_metrics_only_has_no_polyline(self) -> None:
        tools = TravelResearchTools()
        amap = MagicMock()
        amap.enabled = True
        amap.driving_route.return_value = {
            "route": {
                "paths": [
                    {
                        "distance": "120000",
                        "duration": "5400",
                        "steps": [{"instruction": "沿 G30 行驶", "distance": "120000"}],
                    }
                ]
            }
        }
        planner = DayRoutePlanner(_AmapRouteAdapter(tools), amap)
        pois = [
            {"name": "A", "location": "81.0,43.0", "city": "伊犁"},
            {"name": "B", "location": "84.0,43.5", "city": "伊犁"},
        ]
        result = planner.plan(pois, route_profile="driving")
        self.assertEqual(result.status, "metrics_only")
        self.assertFalse(result.draw_path)
        self.assertEqual(result.polyline, [])
        self.assertGreater(result.distance_m, 0)

    def test_ok_with_road_polyline(self) -> None:
        tools = TravelResearchTools()
        amap = MagicMock()
        amap.enabled = True
        amap.driving_route.return_value = {
            "route": {
                "paths": [
                    {
                        "distance": "5000",
                        "duration": "600",
                        "steps": [
                            {"polyline": "115.88,28.68;115.89,28.69;115.90,28.70", "instruction": "向东", "distance": "5000"},
                        ],
                    }
                ]
            }
        }
        planner = DayRoutePlanner(_AmapRouteAdapter(tools), amap)
        pois = [
            {"name": "A", "location": "115.88,28.68", "city": "南昌"},
            {"name": "B", "location": "115.90,28.70", "city": "南昌"},
        ]
        result = planner.plan(pois, route_profile="driving")
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.draw_path)
        self.assertGreaterEqual(len(result.polyline), 2)

    def test_ok_with_minimal_two_point_polyline(self) -> None:
        """部分路径段只返回起终两点，仍视为可绘道路折线（好过完全无线）。"""
        tools = TravelResearchTools()
        amap = MagicMock()
        amap.enabled = True
        amap.driving_route.return_value = {
            "route": {
                "paths": [
                    {
                        "distance": "8000",
                        "duration": "900",
                        "steps": [{"polyline": "115.88,28.68;115.90,28.70", "instruction": "向东", "distance": "8000"}],
                    }
                ]
            }
        }
        planner = DayRoutePlanner(_AmapRouteAdapter(tools), amap)
        pois = [
            {"name": "A", "location": "115.88,28.68", "city": "南昌"},
            {"name": "B", "location": "115.90,28.70", "city": "南昌"},
        ]
        result = planner.plan(pois, route_profile="driving")
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.draw_path)
        self.assertEqual(len(result.polyline), 2)

    def test_single_poi_no_route(self) -> None:
        tools = TravelResearchTools()
        amap = MagicMock()
        amap.enabled = True
        planner = DayRoutePlanner(_AmapRouteAdapter(tools), amap)
        result = planner.plan([{"name": "A", "location": "81.0,43.0"}], route_profile="driving")
        self.assertEqual(result.status, "no_waypoints")


if __name__ == "__main__":
    unittest.main()
