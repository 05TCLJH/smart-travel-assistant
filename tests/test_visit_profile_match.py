"""游览画像匹配：提高命中率。"""

from __future__ import annotations

import unittest

from backend.knowledge.destination_catalog import visit_profiles_for_destination
from backend.knowledge.visit_profiles import match_visit_profile, normalize_poi_name_for_match
from backend.planning.activity_load import enrich_poi_with_activity_load


class VisitProfileMatchTests(unittest.TestCase):
    def test_normalize_strips_store_suffix(self) -> None:
        self.assertNotIn("店", normalize_poi_name_for_match("宽窄巷子旗舰店"))

    def test_long_poi_matches_seed(self) -> None:
        profiles = visit_profiles_for_destination("南昌")
        matched = match_visit_profile("南昌八一起义纪念馆陈列大楼", profiles)
        self.assertIsNotNone(matched)
        self.assertLessEqual(matched["visit_hours"], 3.5)

    def test_enrich_prefers_knowledge_over_generic_two_hours(self) -> None:
        profiles = visit_profiles_for_destination("重庆")
        poi = enrich_poi_with_activity_load(
            {"name": "洪崖洞民俗风貌区", "type": "风景名胜"},
            destination="重庆",
            visit_profiles=profiles,
        )
        self.assertIn(poi.get("activity_load_source"), ("knowledge", "guide"))
        self.assertNotEqual(poi.get("visit_hours"), 2.0)

    def test_museum_poi_uses_guide_when_no_seed_match(self) -> None:
        profiles = visit_profiles_for_destination("南昌")
        poi = enrich_poi_with_activity_load(
            {"name": "某冷门人物纪念馆", "type": "博物馆"},
            destination="南昌",
            visit_profiles=profiles,
        )
        self.assertEqual(poi.get("activity_load_source"), "guide")
        self.assertLessEqual(poi.get("visit_hours"), 3.0)


if __name__ == "__main__":
    unittest.main()
