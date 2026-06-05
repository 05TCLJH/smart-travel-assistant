"""景点类型与排期：北京样例与草原湖泊回归。"""

from __future__ import annotations

import re
import unittest

from backend.knowledge.guide_visit_estimate import estimate_guide_visit
from backend.planning.activity_load import enrich_poi_with_activity_load
from backend.planning.day_schedule import build_activity_timeline
from backend.planning.venue_archetype import resolve_venue_archetype


class VenueArchetypeTests(unittest.TestCase):
    def test_jingshan_not_five_hours(self) -> None:
        m = estimate_guide_visit("景山公园")
        self.assertEqual(m["venue_archetype"], "urban_park_view")
        self.assertLessEqual(m["visit_hours"], 1.6)
        self.assertGreaterEqual(m["visit_hours"], 1.2)

    def test_temple_of_heaven_heritage_park(self) -> None:
        m = estimate_guide_visit("天坛公园")
        self.assertEqual(m["venue_archetype"], "heritage_park")
        self.assertAlmostEqual(m["visit_hours"], 2.0, places=1)

    def test_forbidden_city_hours(self) -> None:
        m = estimate_guide_visit("故宫博物院")
        self.assertEqual(m["venue_archetype"], "palace_museum")
        self.assertLessEqual(m["visit_hours"], 3.6)
        self.assertGreaterEqual(m["visit_hours"], 3.0)

    def test_national_museum_morning_feasible(self) -> None:
        poi = enrich_poi_with_activity_load({"name": "中国国家博物馆", "type": "博物馆"})
        timeline = build_activity_timeline(
            [
                enrich_poi_with_activity_load({"name": "天安门广场", "type": "风景名胜"}),
                poi,
            ]
        )
        row = next(r for r in timeline if "国家博物馆" in r.get("activity", ""))
        start = int(row["time"].split(":")[0]) * 60 + int(row["time"].split(":")[1])
        hours = float(re.search(r"约 ([\d.]+) 小时", row["activity"]).group(1))
        queue = int(poi.get("queue_buffer_min", 0) or 0)
        self.assertLessEqual(start + queue + int(hours * 60), 16 * 60, row["activity"])
        self.assertLess(start, 13 * 60, "国博不宜下午才排队入馆")

    def test_viewpoint_park_ordered_after_main_sites(self) -> None:
        timeline = build_activity_timeline(
            [
                enrich_poi_with_activity_load({"name": "景山公园"}),
                enrich_poi_with_activity_load({"name": "故宫博物院"}),
            ]
        )
        times = {
            r["place"]: int(r["time"].split(":")[0]) * 60 + int(r["time"].split(":")[1])
            for r in timeline
            if r.get("place")
        }
        self.assertLess(times["故宫博物院"], times["景山公园"])

    def test_lake_grassland_still_half_day(self) -> None:
        for name in ("赛里木湖", "那拉提草原"):
            m = estimate_guide_visit(name)
            self.assertEqual(m["activity_tier"], "half_day")
            self.assertGreaterEqual(m["visit_hours"], 4.5)

    def test_tiananmen_square_light(self) -> None:
        spec = resolve_venue_archetype("天安门广场")
        self.assertEqual(spec.archetype, "city_square")
        self.assertAlmostEqual(spec.visit_hours, 1.2, places=1)

    def test_taishan_short_name_not_two_hours(self) -> None:
        m = estimate_guide_visit("泰山")
        self.assertEqual(m["venue_archetype"], "scenic_full_day")
        self.assertGreaterEqual(m["visit_hours"], 6.5)

    def test_taishan_scenic_region_bonus(self) -> None:
        city = resolve_venue_archetype("泰山", region_type="city")
        scenic = resolve_venue_archetype("泰山", region_type="scenic_region")
        self.assertGreater(scenic.visit_hours, city.visit_hours)

    def test_wudang_half_day_peak(self) -> None:
        m = estimate_guide_visit("武当山")
        self.assertEqual(m["venue_archetype"], "scenic_half_day")
        self.assertGreaterEqual(m["visit_hours"], 4.5)

    def test_jingshan_still_urban_not_taishan_rule(self) -> None:
        self.assertEqual(resolve_venue_archetype("景山公园").archetype, "urban_park_view")

    def test_red_hill_park_does_not_get_forbidden_city_pairing(self) -> None:
        spec = resolve_venue_archetype("红山公园")
        self.assertEqual(spec.archetype, "urban_park_view")
        self.assertEqual(spec.pairing_role, "standalone")

    def test_remote_ecological_grassland_park_is_half_day(self) -> None:
        poi = enrich_poi_with_activity_load(
            {
                "name": "乌鲁木齐市苜蓿台生态公园",
                "type": "风景名胜;公园广场",
                "distance_to_destination_km": 40,
            },
            force=True,
        )
        self.assertEqual(poi["venue_archetype"], "scenic_half_day")
        self.assertEqual(poi["activity_tier"], "half_day")
        self.assertGreaterEqual(poi["visit_hours"], 5.0)


if __name__ == "__main__":
    unittest.main()
