"""住宿分配回归测试。"""

from __future__ import annotations

import math
import unittest

from backend.tools.local_service_tools import LocalServiceTools


class _StubAmap:
    enabled = False


class _HotelRetryAmap:
    enabled = True

    def around_search(self, keywords, location, radius=3000):  # type: ignore[no-untyped-def]
        text = str(location)
        if text.startswith("100."):
            return {
                "pois": [
                    {
                        "name": "张掖湿地假日酒店",
                        "type": "住宿服务;宾馆酒店;宾馆酒店",
                        "address": "甘州区湿地公园附近",
                        "location": "100.456,38.936",
                        "pname": "甘肃省",
                        "cityname": "张掖市",
                        "adname": "甘州区",
                        "biz_ext": {"rating": "4.7"},
                    }
                ]
            }
        return {
            "pois": [
                {
                    "name": "冶力关山景酒店",
                    "type": "住宿服务;宾馆酒店;宾馆酒店",
                    "address": "冶力关镇游客中心附近",
                    "location": "103.512,34.982",
                    "pname": "甘肃省",
                    "cityname": "甘南藏族自治州",
                    "adname": "临潭县",
                    "biz_ext": {"rating": "4.6"},
                }
            ]
        }

    def text_search(self, keywords, city="", **kwargs):  # type: ignore[no-untyped-def]
        return {"pois": []}

    def geocode(self, address):  # type: ignore[no-untyped-def]
        return {"geocodes": []}


class _StubResearchTools:
    amap = _StubAmap()

    @staticmethod
    def parse_lnglat(value: str):
        text = str(value or "").strip()
        if "," not in text:
            return None
        lng, lat = text.split(",", 1)
        return float(lng), float(lat)

    @staticmethod
    def distance_km(a, b):
        if not a or not b:
            return 0.0
        return round(math.hypot((a[0] - b[0]) * 85, (a[1] - b[1]) * 111), 2)


class LocalServiceToolsTests(unittest.TestCase):
    """验证远距离日程会触发换住，而不是机械地全程同一家。"""

    def test_assign_lodging_days_switches_when_next_day_far_away(self) -> None:
        tools = LocalServiceTools(_StubResearchTools())
        lodgings = [
            {
                "name": "武昌近景酒店",
                "location": "114.305,30.548",
                "address": "武昌区",
                "rating": "4.8",
                "zone_days": [1],
            },
            {
                "name": "汉口近景酒店",
                "location": "114.270,30.610",
                "address": "江岸区",
                "rating": "4.7",
                "zone_days": [2],
            },
        ]
        plan = {
            "itinerary": [
                {
                    "route_waypoints": [
                        {"name": "黄鹤楼公园", "location": "114.306,30.547", "district": "武昌区"},
                        {"name": "湖北省博物馆", "location": "114.367,30.560", "district": "武昌区"},
                    ]
                },
                {
                    "route_waypoints": [
                        {"name": "汉口江滩", "location": "114.292,30.607", "district": "江岸区"},
                        {"name": "黎黄陂路", "location": "114.298,30.596", "district": "江岸区"},
                    ]
                },
            ]
        }

        hotels, daily_stays = tools.assign_lodging_days(lodgings, plan, 2)

        self.assertEqual(daily_stays[0]["hotel_name"], "武昌近景酒店")
        self.assertEqual(daily_stays[1]["hotel_name"], "汉口近景酒店")
        labels = {hotel["name"]: hotel.get("stay_label", "") for hotel in hotels}
        self.assertEqual(labels["武昌近景酒店"], "Day 1")
        self.assertEqual(labels["汉口近景酒店"], "Day 2")

    def test_normalize_food_rows_hides_numeric_amap_type_code(self) -> None:
        tools = LocalServiceTools(_StubResearchTools())

        foods = tools._normalize_food_rows(
            [
                {
                    "name": "老街早点铺",
                    "type": "050100",
                    "address": "江岸区老街 18 号",
                    "location": "114.300,30.600",
                    "cityname": "武汉",
                    "adname": "江岸区",
                    "biz_ext": {"rating": "4.6", "cost": "22"},
                }
            ],
            "武汉",
            (114.300, 30.600),
        )

        self.assertEqual(len(foods), 1)
        self.assertEqual(foods[0]["type"], "中餐厅")
        self.assertEqual(foods[0]["type_code"], "050100")

    def test_budget_style_changes_lodging_queries_and_fallback_types(self) -> None:
        tools = LocalServiceTools(_StubResearchTools())

        luxury_queries = tools._lodging_queries("上海", "高品质")
        comfort_queries = tools._lodging_queries("上海", "品质")
        luxury_rows = tools._fallback_lodgings("上海", "高品质", 3)

        self.assertIn("上海五星级酒店", luxury_queries)
        self.assertIn("上海豪华型酒店", comfort_queries)
        self.assertEqual(luxury_rows[0]["budget_tier"], "高品质")
        self.assertEqual(luxury_rows[0]["type"], "豪华酒店")

    def test_normalize_lodging_rows_accepts_province_level_destination(self) -> None:
        tools = LocalServiceTools(_StubResearchTools())

        hotels = tools._normalize_lodging_rows(
            [
                {
                    "name": "张掖湿地假日酒店",
                    "type": "住宿服务;宾馆酒店;宾馆酒店",
                    "address": "甘州区湿地公园附近",
                    "location": "100.456,38.936",
                    "pname": "甘肃省",
                    "cityname": "张掖市",
                    "adname": "甘州区",
                    "biz_ext": {"rating": "4.7"},
                }
            ],
            "甘肃",
            None,
            "舒适",
        )

        self.assertEqual(len(hotels), 1)
        self.assertEqual(hotels[0]["name"], "张掖湿地假日酒店")

    def test_assign_lodging_days_keeps_same_hotel_when_distance_gap_is_small(self) -> None:
        tools = LocalServiceTools(_StubResearchTools())
        lodgings = [
            {
                "name": "武昌核心酒店",
                "location": "114.310,30.550",
                "address": "武昌区",
                "district": "武昌区",
                "rating": "4.8",
                "zone_days": [1, 2],
            },
            {
                "name": "武昌东侧酒店",
                "location": "114.319,30.553",
                "address": "武昌区",
                "district": "武昌区",
                "rating": "4.7",
                "zone_days": [2],
            },
        ]
        plan = {
            "itinerary": [
                {
                    "route_waypoints": [
                        {"name": "黄鹤楼公园", "location": "114.306,30.547", "district": "武昌区"},
                        {"name": "湖北省博物馆", "location": "114.367,30.560", "district": "武昌区"},
                    ]
                },
                {
                    "route_waypoints": [
                        {"name": "武昌江边步道", "location": "114.318,30.551", "district": "武昌区"},
                        {"name": "老城区慢逛街区", "location": "114.324,30.552", "district": "武昌区"},
                    ]
                },
            ]
        }

        hotels, daily_stays = tools.assign_lodging_days(lodgings, plan, 2)

        self.assertEqual(daily_stays[0]["hotel_name"], "武昌核心酒店")
        self.assertEqual(daily_stays[1]["hotel_name"], "武昌核心酒店")
        labels = {hotel["name"]: hotel.get("stay_label", "") for hotel in hotels}
        self.assertEqual(labels["武昌核心酒店"], "Day 1-2")

    def test_assign_lodging_days_switches_when_daily_best_hotel_changes_significantly(self) -> None:
        tools = LocalServiceTools(_StubResearchTools())
        lodgings = [
            {
                "name": "九峰附近酒店",
                "location": "114.470,30.510",
                "address": "东湖高新区",
                "district": "东湖高新区",
                "rating": "4.8",
                "zone_days": [1],
            },
            {
                "name": "江夏青龙山酒店",
                "location": "114.360,30.360",
                "address": "江夏区",
                "district": "江夏区",
                "rating": "4.7",
                "zone_days": [2, 3],
            },
            {
                "name": "月湖景区酒店",
                "location": "114.240,30.560",
                "address": "汉阳区",
                "district": "汉阳区",
                "rating": "4.9",
                "zone_days": [4],
            },
        ]
        plan = {
            "itinerary": [
                {"route_waypoints": [{"name": "九峰国家森林公园", "location": "114.468,30.512", "district": "东湖高新区"}]},
                {"route_waypoints": [{"name": "江夏区青龙山国家森林公园", "location": "114.355,30.362", "district": "江夏区"}]},
                {"route_waypoints": [{"name": "设法山登山步道", "location": "114.348,30.374", "district": "江夏区"}]},
                {"route_waypoints": [{"name": "月湖风景区", "location": "114.236,30.558", "district": "汉阳区"}]},
            ]
        }

        hotels, daily_stays = tools.assign_lodging_days(lodgings, plan, 4)

        self.assertEqual([stay["hotel_name"] for stay in daily_stays], ["九峰附近酒店", "江夏青龙山酒店", "江夏青龙山酒店", "月湖景区酒店"])
        labels = {hotel["name"]: hotel.get("stay_label", "") for hotel in hotels}
        self.assertEqual(labels["九峰附近酒店"], "Day 1")
        self.assertEqual(labels["江夏青龙山酒店"], "Day 2-3")
        self.assertEqual(labels["月湖景区酒店"], "Day 4")

    def test_assign_lodging_penalizes_far_day_endpoint(self) -> None:
        tools = LocalServiceTools(_StubResearchTools())
        lodgings = [
            {
                "name": "老城酒店",
                "location": "87.620,43.800",
                "address": "红山附近",
                "district": "天山区",
                "rating": "4.8",
                "zone_days": [1],
            },
            {
                "name": "南山落脚酒店",
                "location": "87.360,43.610",
                "address": "南山附近",
                "district": "乌鲁木齐县",
                "rating": "4.6",
                "zone_days": [2],
            },
        ]
        plan = {
            "itinerary": [
                {"route_waypoints": [{"name": "红山公园", "location": "87.613,43.802", "district": "天山区"}]},
                {
                    "route_waypoints": [
                        {"name": "市区早餐点", "location": "87.620,43.800", "district": "天山区"},
                        {"name": "乌鲁木齐市苜蓿台生态公园", "location": "87.360,43.610", "district": "乌鲁木齐县"},
                    ]
                },
            ]
        }

        _, daily_stays = tools.assign_lodging_days(lodgings, plan, 2)

        self.assertEqual(daily_stays[0]["hotel_name"], "老城酒店")
        self.assertEqual(daily_stays[1]["hotel_name"], "南山落脚酒店")

    def test_assign_lodging_completes_exact_hotels_for_province_route(self) -> None:
        class _ResearchWithHotelRetry(_StubResearchTools):
            amap = _HotelRetryAmap()

        tools = LocalServiceTools(_ResearchWithHotelRetry())
        lodgings = [
            {
                "name": "鑫海假日酒店",
                "location": "103.740,36.060",
                "address": "兰州市",
                "district": "七里河区",
                "rating": "4.6",
                "zone_days": [3],
            }
        ]
        plan = {
            "itinerary": [
                {"route_waypoints": [{"name": "冶力关国家森林公园", "location": "103.510,34.980", "district": "临潭县", "city": "甘南藏族自治州"}]},
                {"route_waypoints": [{"name": "张掖国家湿地公园", "location": "100.455,38.935", "district": "甘州区", "city": "张掖市"}]},
                {"route_waypoints": [{"name": "甘肃地质博物馆", "location": "103.739,36.061", "district": "七里河区", "city": "兰州市"}]},
            ]
        }

        hotels, daily_stays = tools.assign_lodging_days(lodgings, plan, 3)

        self.assertNotIn("冶力关国家森林公园周边住宿片区", [hotel["name"] for hotel in hotels])
        self.assertNotIn("张掖国家湿地公园周边住宿片区", [hotel["name"] for hotel in hotels])
        self.assertEqual(
            [stay["hotel_name"] for stay in daily_stays],
            ["冶力关山景酒店", "张掖湿地假日酒店", "鑫海假日酒店"],
        )
        self.assertEqual(daily_stays[0]["lodging_status"], "ok")
        self.assertEqual(daily_stays[1]["lodging_status"], "ok")
        self.assertFalse(daily_stays[0]["is_lodging_zone_suggestion"])
        self.assertFalse(daily_stays[1]["is_lodging_zone_suggestion"])
        self.assertFalse(daily_stays[2]["is_lodging_zone_suggestion"])

    def test_first_night_considers_next_day_first_stop(self) -> None:
        tools = LocalServiceTools(_StubResearchTools())
        lodgings = [
            {
                "name": "当天中心酒店",
                "location": "120.100,30.100",
                "address": "第一天活动中心",
                "rating": "4.8",
            },
            {
                "name": "次日首站顺路酒店",
                "location": "120.250,30.100",
                "address": "两日之间顺路位置",
                "rating": "4.7",
            },
        ]
        plan = {
            "itinerary": [
                {
                    "route_waypoints": [
                        {"name": "第一天上午点", "location": "120.050,30.100"},
                        {"name": "第一天终点", "location": "120.200,30.100"},
                    ]
                },
                {
                    "route_waypoints": [
                        {"name": "第二天首站", "location": "120.300,30.100"},
                        {"name": "第二天下午点", "location": "120.320,30.100"},
                    ]
                },
            ]
        }

        _, daily_stays = tools.assign_lodging_days(lodgings, plan, 2)

        self.assertEqual(daily_stays[0]["hotel_name"], "次日首站顺路酒店")
        self.assertIn("明早去 第二天首站", daily_stays[0]["reason"])

    def test_assign_lodging_retries_real_hotels_before_zone_placeholder(self) -> None:
        class _ResearchWithHotelRetry(_StubResearchTools):
            amap = _HotelRetryAmap()

        tools = LocalServiceTools(_ResearchWithHotelRetry())
        plan = {
            "itinerary": [
                {"route_waypoints": [{"name": "冶力关国家森林公园", "location": "103.510,34.980", "district": "临潭县", "city": "甘南藏族自治州"}]},
            ]
        }

        hotels, daily_stays = tools.assign_lodging_days([], plan, 1)

        self.assertEqual(daily_stays[0]["hotel_name"], "冶力关山景酒店")
        self.assertFalse(daily_stays[0]["is_lodging_zone_suggestion"])
        self.assertIn("冶力关山景酒店", [hotel["name"] for hotel in hotels])


if __name__ == "__main__":
    unittest.main()
