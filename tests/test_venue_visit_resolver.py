"""统一游览指标解析测试：主题乐园六小时与知识库画像校准。"""

from __future__ import annotations

import unittest

from backend.knowledge.destination_catalog import _load_catalog, merged_visit_profiles_for_destination
from backend.planning.activity_load import enrich_poi_with_activity_load
from backend.planning.venue_archetype import is_theme_park_poi, resolve_venue_archetype_from_poi
from backend.planning.venue_visit_resolver import resolve_poi_visit_metrics


class VenueVisitResolverTests(unittest.TestCase):
    def test_theme_park_archetype_six_hours(self) -> None:
        for name in ("深圳世界之窗", "北京欢乐谷", "上海迪士尼度假区"):
            m = resolve_poi_visit_metrics({"name": name, "type": "体育休闲服务;游乐园"})
            self.assertEqual(m["venue_archetype"], "theme_park")
            self.assertEqual(m["schedule_mode"], "theme_park")
            self.assertAlmostEqual(m["visit_hours"], 6.0, places=1)
            self.assertEqual(m["activity_tier"], "half_day")
            self.assertGreaterEqual(m["activity_load"], 68)

    def test_knowledge_profile_cannot_downgrade_theme_park(self) -> None:
        _load_catalog.cache_clear()
        profiles = merged_visit_profiles_for_destination("深圳")
        poi = enrich_poi_with_activity_load(
            {"name": "世界之窗", "type": "风景名胜"},
            destination="深圳",
            visit_profiles=profiles,
        )
        self.assertEqual(poi["venue_archetype"], "theme_park")
        self.assertAlmostEqual(poi["visit_hours"], 6.0, places=1)
        self.assertEqual(poi["schedule_mode"], "theme_park")

    def test_creative_park_not_theme_park(self) -> None:
        spec = resolve_venue_archetype_from_poi({"name": "华侨城创意文化园"})
        self.assertNotEqual(spec.archetype, "theme_park")

    def test_typecode_amusement_is_theme_park(self) -> None:
        spec = resolve_venue_archetype_from_poi(
            {"name": "某主题乐园", "type": "", "typecode": "080501"}
        )
        self.assertEqual(spec.archetype, "theme_park")

    def test_ordinary_park_not_theme_park(self) -> None:
        for name in ("人民公园", "世纪公园", "滨江公园", "中山公园"):
            self.assertFalse(is_theme_park_poi(name))
            spec = resolve_venue_archetype_from_poi({"name": name})
            self.assertIn(spec.archetype, ("urban_park_view", "heritage_park"))
            m = resolve_poi_visit_metrics({"name": name})
            self.assertLessEqual(m["visit_hours"], 2.5)
            self.assertNotEqual(m.get("schedule_mode"), "theme_park")

    def test_auxiliary_gate_is_light(self) -> None:
        m = resolve_poi_visit_metrics({"name": "黄山风景区南大门售票处", "type": "生活服务"})
        self.assertLessEqual(m["activity_load"], 25)

    def test_yuelu_mountain_is_city_hill_not_full_day(self) -> None:
        m = resolve_poi_visit_metrics({"name": "岳麓山风景名胜区", "type": "风景名胜"})
        self.assertEqual(m["venue_archetype"], "scenic_city_hill")
        self.assertAlmostEqual(m["visit_hours"], 3.5, places=1)
        self.assertEqual(m["activity_tier"], "extended")
        self.assertLess(m["visit_hours"], 5.0)

    def test_huangshan_remains_full_day(self) -> None:
        m = resolve_poi_visit_metrics({"name": "黄山风景区", "type": "风景名胜"})
        self.assertEqual(m["venue_archetype"], "scenic_full_day")
        self.assertGreaterEqual(m["visit_hours"], 6.5)


if __name__ == "__main__":
    unittest.main()
