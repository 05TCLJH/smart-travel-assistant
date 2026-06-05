"""日程时间轴：时长合理、馆内行程不被午餐打断。"""

from __future__ import annotations

import re
import unittest

from backend.planning.activity_load import enrich_poi_with_activity_load
from backend.planning.day_schedule import build_activity_timeline
from backend.knowledge.destination_catalog import merged_visit_profiles_for_destination


class DayScheduleTests(unittest.TestCase):
    def test_museum_hours_not_six_from_half_day_tier(self) -> None:
        poi = enrich_poi_with_activity_load(
            {"name": "江西省博物馆", "type": "博物馆"},
            destination="南昌",
            visit_profiles=merged_visit_profiles_for_destination("南昌"),
        )
        self.assertLessEqual(poi["visit_hours"], 3.5)
        self.assertEqual(poi["schedule_mode"], "contiguous_gate")

    def test_memorial_timeline_lunch_not_inside_visit_block(self) -> None:
        memorial = enrich_poi_with_activity_load(
            {"name": "南昌八一起义纪念馆陈列大楼", "type": "博物馆"},
            destination="南昌",
            visit_profiles=merged_visit_profiles_for_destination("南昌"),
        )
        temple = enrich_poi_with_activity_load(
            {"name": "佑民寺", "type": "风景名胜;寺庙"},
            destination="南昌",
            visit_profiles=merged_visit_profiles_for_destination("南昌"),
        )
        self.assertLessEqual(memorial["visit_hours"], 3.5)
        timeline = build_activity_timeline([memorial, temple])
        visit_rows = [r for r in timeline if "游览" in r.get("activity", "")]
        lunch_rows = [r for r in timeline if "午餐" in r.get("activity", "")]
        self.assertTrue(lunch_rows)
        memorial_row = next(r for r in visit_rows if "八一起义" in r["activity"])
        hours = float(re.search(r"约 ([\d.]+) 小时", memorial_row["activity"]).group(1))
        self.assertLessEqual(hours, 3.5)
        start = int(memorial_row["time"].split(":")[0]) * 60 + int(memorial_row["time"].split(":")[1])
        end = start + int(hours * 60)
        for lunch in lunch_rows:
            lm = int(lunch["time"].split(":")[0]) * 60 + int(lunch["time"].split(":")[1])
            self.assertFalse(start < lm < end, f"lunch {lunch['time']} inside visit {memorial_row['time']}")

    def test_museum_starts_in_morning_when_reordered(self) -> None:
        fountain = enrich_poi_with_activity_load(
            {"name": "南昌秋水广场音乐喷泉", "type": "风景名胜"},
            destination="南昌",
        )
        museum = enrich_poi_with_activity_load(
            {"name": "江西省博物馆", "type": "博物馆"},
            destination="南昌",
            visit_profiles=merged_visit_profiles_for_destination("南昌"),
        )
        timeline = build_activity_timeline([fountain, museum])
        museum_row = next(r for r in timeline if "江西省博物馆" in r.get("activity", ""))
        museum_start = int(museum_row["time"].split(":")[0]) * 60 + int(museum_row["time"].split(":")[1])
        self.assertLess(museum_start, 12 * 60, "博物馆应优先上午入馆")
        hours = float(re.search(r"约 ([\d.]+) 小时", museum_row["activity"]).group(1))
        queue = int(museum.get("queue_buffer_min", 0) or 0)
        self.assertLessEqual(museum_start + queue + int(hours * 60), 16 * 60)


    def test_palace_jingshan_has_morning_visit_not_blank_am(self) -> None:
        palace = enrich_poi_with_activity_load({"name": "故宫博物院", "type": "博物馆"})
        jingshan = enrich_poi_with_activity_load({"name": "景山公园", "type": "公园"})
        timeline = build_activity_timeline([palace, jingshan])
        visit_rows = [r for r in timeline if "游览" in r.get("activity", "")]
        self.assertTrue(visit_rows)
        first_visit = visit_rows[0]
        start_h, start_m = map(int, first_visit["time"].split(":"))
        self.assertLess(start_h * 60 + start_m, 12 * 60, first_visit)
        self.assertTrue(any("午餐" in r.get("activity", "") for r in timeline))

    def test_afternoon_scenic_visit_omits_midday_supply_note(self) -> None:
        museum = enrich_poi_with_activity_load(
            {"name": "江西省博物馆", "type": "博物馆"},
            destination="南昌",
            visit_profiles=merged_visit_profiles_for_destination("南昌"),
        )
        scenic = enrich_poi_with_activity_load(
            {"name": "艾溪湖森林湿地公园", "type": "风景名胜"},
            destination="南昌",
            visit_profiles=merged_visit_profiles_for_destination("南昌"),
        )
        timeline = build_activity_timeline([museum, scenic])
        scenic_row = next(r for r in timeline if "艾溪湖" in r.get("activity", ""))
        self.assertNotIn("午间更适合", scenic_row["activity"])
        self.assertNotIn("景区内简餐", scenic_row["activity"])

    def test_timeline_uses_coordinate_transit_for_far_points(self) -> None:
        muxutai = enrich_poi_with_activity_load(
            {
                "name": "乌鲁木齐市苜蓿台生态公园",
                "type": "风景名胜;公园广场",
                "location": "87.360,43.610",
                "distance_to_destination_km": 40,
            },
            force=True,
        )
        hongshan = enrich_poi_with_activity_load(
            {"name": "红山公园", "type": "公园", "location": "87.613,43.802"},
            force=True,
        )
        timeline = build_activity_timeline([muxutai, hongshan])
        travel_row = next(row for row in timeline if "前往 红山公园" in row.get("activity", ""))
        self.assertRegex(travel_row["activity"], r"约 (6[0-9]|7[0-9]|8[0-9]) 分钟")
        hongshan_row = next(row for row in timeline if "游览 红山公园" in row.get("activity", ""))
        start = int(hongshan_row["time"].split(":")[0]) * 60 + int(hongshan_row["time"].split(":")[1])
        self.assertGreaterEqual(start, 15 * 60)


if __name__ == "__main__":
    unittest.main()
