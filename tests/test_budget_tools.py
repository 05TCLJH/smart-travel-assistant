"""预算明细与贴心提醒生成测试。"""

from __future__ import annotations

import unittest

from backend.tools.budget_tools import build_budget_breakdown, build_tips


class BudgetToolsTests(unittest.TestCase):
    """验证估算版门票预算与提醒文案。"""

    def test_budget_breakdown_marks_all_ticket_sources_as_estimated(self) -> None:
        itinerary = [
            {
                "route_waypoints": [
                    {"name": "象鼻山景区", "type": "风景名胜", "ticket": "120"},
                    {"name": "阳朔西街", "type": "风景名胜", "ticket": "未知"},
                ]
            }
        ]
        result = build_budget_breakdown(
            {"days": 2, "budget": 5000},
            {"companions": 2, "budget_style": "舒适", "transport_preference": "打车/网约车优先"},
            itinerary,
        )

        ticket_detail = result["budget_detail"]["tickets"]
        self.assertEqual(ticket_detail["summary"]["live_price_count"], 0)
        self.assertEqual(ticket_detail["summary"]["estimated_count"], 2)
        self.assertTrue(all(line["source_type"] == "estimated" for line in ticket_detail["lines"]))
        self.assertIn("预算估算值", result["budget_note"])
        self.assertIn("官方预约页", result["budget_note"])

    def test_build_tips_returns_warm_structured_cards(self) -> None:
        itinerary = [
            {
                "day": 1,
                "route_points": ["象鼻山景区", "阳朔西街"],
                "route_waypoints": [
                    {"name": "象鼻山景区", "type": "风景名胜", "ticket": "120"},
                    {"name": "阳朔西街", "type": "风景名胜", "ticket": "未知"},
                ],
            }
        ]
        budget = build_budget_breakdown(
            {"days": 3, "budget": 6000},
            {"companions": 2, "budget_style": "舒适", "transport_preference": "打车/网约车优先"},
            itinerary,
        )
        plan = {
            **budget,
            "itinerary": itinerary,
            "preferred_places": ["象鼻山景区", "阳朔西街"],
        }

        cards = build_tips(
            {"rating": "良好", "daily": []},
            plan,
            {"destination": "桂林", "days": 3, "start_date": "2026-05-30"},
            {
                "stamina": "适中",
                "companions": 2,
                "transport_preference": "打车/网约车优先",
                "must_have": ["不绕路", "节奏清晰"],
                "dietary_restrictions": "不吃香菜",
            },
            {
                "daily_stays": [
                    {"day": 1, "hotel_name": "象山地铁口酒店", "distance_to_day_center_km": 1.2},
                    {"day": 2, "hotel_name": "十字街地铁口酒店", "distance_to_day_center_km": 1.6},
                ]
            },
            [
                {"name": "象山地铁口酒店", "stay_label": "Day 1", "is_primary": True},
                {"name": "十字街地铁口酒店", "stay_label": "Day 2", "is_primary": True},
            ],
        )

        self.assertTrue(cards)
        self.assertTrue(all(isinstance(item, dict) for item in cards))
        joined = " ".join(f"{item.get('title', '')} {item.get('body', '')}" for item in cards)
        self.assertNotIn("画像里是", joined)
        self.assertNotIn("我已", joined)
        self.assertNotIn("不绕路", joined)
        self.assertNotIn("节奏清晰", joined)
        self.assertNotIn("不吃香菜", joined)
        self.assertIn("象鼻山景区", joined)
        self.assertTrue(any(item.get("tag") == "住宿" for item in cards))
        self.assertTrue(any(item.get("layout") == "featured" for item in cards))
        self.assertIn("地铁", joined)

    def test_high_quality_budget_style_has_higher_budget_multiplier(self) -> None:
        itinerary = [{"route_waypoints": [{"name": "黄鹤楼", "type": "风景名胜"}]}]

        comfort = build_budget_breakdown(
            {"days": 2, "budget": 8000},
            {"companions": 2, "budget_style": "品质", "transport_preference": "打车/网约车优先"},
            itinerary,
        )
        luxury = build_budget_breakdown(
            {"days": 2, "budget": 8000},
            {"companions": 2, "budget_style": "高品质", "transport_preference": "打车/网约车优先"},
            itinerary,
        )

        self.assertGreater(luxury["cost_breakdown"]["住宿"], comfort["cost_breakdown"]["住宿"])
        self.assertGreater(luxury["estimated_total_cost"], comfort["estimated_total_cost"])

    def test_xinjiang_tips_include_region_practical_context(self) -> None:
        plan = {
            "itinerary": [
                {
                    "day": 1,
                    "route_points": ["乌鲁木齐市苜蓿台生态公园"],
                    "route_waypoints": [
                        {
                            "name": "乌鲁木齐市苜蓿台生态公园",
                            "type": "风景名胜;公园广场",
                            "city": "乌鲁木齐市",
                            "address": "新疆乌鲁木齐南郊",
                            "location": "87.360,43.610",
                            "distance_to_destination_km": 40,
                        }
                    ],
                }
            ]
        }

        cards = build_tips(
            {"rating": "良好", "daily": []},
            plan,
            {"destination": "乌鲁木齐", "days": 3},
            {"stamina": "适中", "companions": 1},
        )

        joined = " ".join(f"{item.get('title', '')} {item.get('body', '')}" for item in cards)
        self.assertIn("新疆", joined)
        self.assertIn("身份证", joined)
        self.assertIn("公共交通", joined)


if __name__ == "__main__":
    unittest.main()
