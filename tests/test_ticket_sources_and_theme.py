"""门票来源与主题文案回归测试。"""

from __future__ import annotations

import unittest

from backend.planning.itinerary_builder import summarize_theme
from backend.tools.budget_tools import build_budget_breakdown
from backend.tools.ticket_price_resolver import match_official_ticket_source, resolve_ticket_price_source


class TicketSourcesAndThemeTests(unittest.TestCase):
    """验证估算版门票来源与主题文案。"""

    def test_budget_breakdown_does_not_use_local_ticket_catalog(self) -> None:
        itinerary = [
            {
                "route_waypoints": [
                    {
                        "name": "黄鹤楼公园",
                        "type": "风景名胜",
                        "city": "武汉",
                        "ticket": "未知",
                    }
                ]
            }
        ]
        result = build_budget_breakdown(
            {"destination": "武汉", "days": 2, "budget": 5000},
            {"companions": 1, "budget_style": "舒适", "transport_preference": "打车/网约车优先"},
            itinerary,
        )

        row = result["budget_detail"]["tickets"]["lines"][0]
        self.assertIsNone(match_official_ticket_source("黄鹤楼公园", "武汉"))
        self.assertEqual(row["source_type"], "estimated")
        self.assertFalse(row["source_name"])
        self.assertFalse(row["source_url"])

    def test_estimated_reference_price_does_not_look_like_live_price(self) -> None:
        source = resolve_ticket_price_source(
            {
                "name": "黄鹤楼公园",
                "ticket_reference_price": 80,
                "ticket_source_type": "estimated",
                "ticket_source_label": "经验估算",
            },
            "武汉",
        )

        self.assertIsNone(source["price"])
        self.assertEqual(source["source_type"], "estimated")
        self.assertEqual(source["source_label"], "经验估算")

    def test_summarize_theme_does_not_use_history_line_copy(self) -> None:
        theme = summarize_theme(
            "武汉",
            [{"name": "湖北省博物馆", "type": "博物馆", "knowledge_tags": ["museum"]}],
        )
        self.assertNotIn("历史线", theme)
        self.assertEqual(theme, "武汉 文化地标漫游")


if __name__ == "__main__":
    unittest.main()
