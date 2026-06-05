"""导游时长标准：知识库种子估算。"""

from __future__ import annotations

import unittest

from backend.knowledge.guide_visit_estimate import estimate_guide_visit


class GuideVisitEstimateTests(unittest.TestCase):
    def test_lake_grassland_half_day_hours(self) -> None:
        for name in ("赛里木湖", "那拉提草原", "喀拉峻草原"):
            m = estimate_guide_visit(name)
            self.assertEqual(m["activity_tier"], "half_day")
            self.assertGreaterEqual(m["visit_hours"], 4.5)
            self.assertLessEqual(m["visit_hours"], 6.5)

    def test_bridge_is_light(self) -> None:
        m = estimate_guide_visit("果子沟大桥")
        self.assertEqual(m["activity_tier"], "light")
        self.assertLessEqual(m["visit_hours"], 1.5)

    def test_provincial_museum_capped(self) -> None:
        m = estimate_guide_visit("江西省博物馆")
        self.assertEqual(m["activity_tier"], "half_day")
        self.assertLessEqual(m["visit_hours"], 3.5)

    def test_memorial_not_six_hours(self) -> None:
        m = estimate_guide_visit("南昌八一起义纪念馆陈列大楼")
        self.assertLessEqual(m["visit_hours"], 3.0)

    def test_full_day_mountain(self) -> None:
        m = estimate_guide_visit("黄山风景区")
        self.assertEqual(m["activity_tier"], "full_day")
        self.assertGreaterEqual(m["visit_hours"], 6.5)


if __name__ == "__main__":
    unittest.main()
