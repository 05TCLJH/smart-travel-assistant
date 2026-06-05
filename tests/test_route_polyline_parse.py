"""单元测试：将高德路线响应解码为折线。"""
from __future__ import annotations

import unittest

from backend.tools.amap_tools import TravelResearchTools


class RoutePolylineParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.t = TravelResearchTools()

    def test_standard_route_paths_steps(self) -> None:
        payload = {
            "route": {
                "paths": [
                    {
                        "distance": "1200",
                        "duration": "300",
                        "steps": [
                            {"polyline": "115.88,28.68;115.89,28.69", "instruction": "向东", "distance": "600"},
                            {"polyline": "115.89,28.69;115.90,28.70", "instruction": "过桥", "distance": "600"},
                        ],
                    }
                ]
            }
        }
        seg = self.t._parse_route_segment(payload)
        self.assertEqual(seg["distance_m"], 1200)
        self.assertGreaterEqual(len(seg["polyline"]), 3)

    def test_paths_at_root(self) -> None:
        payload = {
            "paths": [
                {
                    "distance": 500,
                    "duration": 120,
                    "polyline": "115.88,28.68;115.885,28.685;115.89,28.69",
                }
            ]
        }
        seg = self.t._parse_route_segment(payload)
        self.assertGreaterEqual(len(seg["polyline"]), 3)

    def test_nested_data_route(self) -> None:
        payload = {"data": {"route": {"paths": [{"distance": 800, "duration": 200, "steps": [{"polyline": "116.3,39.9;116.31,39.91"}]}]}}}
        seg = self.t._parse_route_segment(payload)
        self.assertGreaterEqual(len(seg["polyline"]), 2)

    def test_tmcs_fallback(self) -> None:
        payload = {
            "route": {
                "paths": [
                    {
                        "distance": 900,
                        "duration": 180,
                        "steps": [],
                        "tmcs": [
                            {"polyline": "115.1,28.1;115.11,28.11"},
                            {"polyline": "115.11,28.11;115.12,28.12"},
                        ],
                    }
                ]
            }
        }
        seg = self.t._parse_route_segment(payload)
        self.assertGreaterEqual(len(seg["polyline"]), 3)


if __name__ == "__main__":
    unittest.main()
