"""景点类型展示清洗测试。"""

from __future__ import annotations

import unittest

from backend.planning.poi_type_display import normalize_poi_type_label
from backend.knowledge.guide_visit_estimate import estimate_guide_visit


class PoiTypeDisplayTests(unittest.TestCase):
    def test_cruise_messy_amap_type(self) -> None:
        raw = "交通设施服务; 港口码头; 港口码头|风景名胜; 风景名胜"
        label = normalize_poi_type_label(raw, poi_name="海河游船(天津站码头)")
        self.assertEqual(label, "游船体验")

    def test_haihe_cruise_hours_not_half_day(self) -> None:
        m = estimate_guide_visit("海河游船(天津站码头)")
        self.assertEqual(m["venue_archetype"], "water_experience")
        self.assertLessEqual(m["visit_hours"], 2.0)

    def test_italian_style_street_not_scenic(self) -> None:
        m = estimate_guide_visit("天津意大利风情旅游区")
        self.assertEqual(m["venue_archetype"], "street_district")

    def test_culture_street(self) -> None:
        m = estimate_guide_visit("天津古文化街")
        self.assertEqual(m["venue_archetype"], "street_district")


if __name__ == "__main__":
    unittest.main()
