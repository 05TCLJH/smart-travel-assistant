"""游览点归并测试：同母景区多个子地点收敛为单一锚点。"""

from __future__ import annotations

import unittest

from backend.planning.visit_sites import address_venue_key, merge_to_visit_sites, scenic_cluster_key, visit_site_id


class VisitSiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seeds = {
            "洪崖洞民俗风貌区",
            "解放碑步行街",
            "磁器口古镇",
            "朝天门",
        }

    def test_hongyadong_sub_pois_merge_to_one_anchor(self) -> None:
        pois = [
            {
                "name": "记忆山城",
                "address": "嘉陵江滨江路88号洪崖洞民俗风貌区（东南角）",
                "type": "风景名胜;风景名胜相关;旅游景点",
                "location": "106.578,29.562",
                "suitability_score": 70,
            },
            {
                "name": "洪崖滴翠广场",
                "address": "嘉滨路88号洪崖洞民俗风貌区内1-2层",
                "type": "风景名胜;公园广场;城市广场",
                "location": "106.579,29.563",
                "suitability_score": 68,
            },
            {
                "name": "洪崖洞民俗风貌区",
                "address": "嘉陵江滨江路88号",
                "type": "风景名胜;风景名胜;风景名胜",
                "location": "106.580,29.564",
                "suitability_score": 92,
                "knowledge_seed": True,
            },
            {
                "name": "三将军炮台",
                "address": "嘉陵江滨江路88号洪崖洞民俗风貌区（东北角）",
                "type": "风景名胜;风景名胜相关;旅游景点",
                "location": "106.579,29.563",
                "suitability_score": 65,
            },
            {
                "name": "磁器口古镇",
                "address": "磁器口正街1号",
                "type": "风景名胜;风景名胜;国家级景点",
                "location": "106.450,29.580",
                "suitability_score": 88,
            },
        ]
        merged = merge_to_visit_sites(pois, seed_names=self.seeds, max_per_site=1)
        names = {p["name"] for p in merged}
        self.assertEqual(len(merged), 2, names)
        self.assertIn("洪崖洞民俗风貌区", names)
        self.assertIn("磁器口古镇", names)
        anchor = next(p for p in merged if p["name"] == "洪崖洞民俗风貌区")
        self.assertGreaterEqual(len(anchor.get("visit_site_members", [])), 2)
        self.assertIn("记忆山城", anchor.get("visit_site_members", []))

    def test_address_venue_key_extracts_parent_scenic(self) -> None:
        poi = {"name": "记忆山城", "address": "嘉陵江滨江路88号洪崖洞民俗风貌区（东南角）"}
        key = address_venue_key(poi, self.seeds)
        self.assertTrue(key)
        self.assertEqual(
            visit_site_id(
                {"name": "洪崖洞民俗风貌区", "address": "嘉陵江滨江路88号", "type": "风景名胜"},
                self.seeds,
            ),
            visit_site_id(poi, self.seeds),
        )

    def test_cluster_key_kuanzhai_parenthetical_and_plaza(self) -> None:
        seeds = {"宽窄巷子"}
        cigar = {"name": "长城雪茄(宽窄巷子店)", "type": "风景名胜;特色商业街", "poi_role": "street_landmark"}
        plaza = {"name": "宽窄巷子东广场", "type": "风景名胜", "poi_role": "street_landmark"}
        self.assertEqual(
            scenic_cluster_key(cigar["name"], seeds, poi=cigar),
            scenic_cluster_key(plaza["name"], seeds, poi=plaza),
        )

    def test_west_lake_inner_landmarks_merge_to_parent_site(self) -> None:
        pois = [
            {
                "name": "雷峰塔景区",
                "address": "南山路15号",
                "type": "风景名胜;风景名胜;国家级景点",
                "location": "120.148,30.233",
                "suitability_score": 85,
            },
            {
                "name": "杭州西湖风景名胜区-九溪烟树",
                "address": "龙井村杭州西湖风景名胜区内",
                "type": "风景名胜;风景名胜;风景名胜",
                "location": "120.105,30.212",
                "suitability_score": 90,
            },
            {
                "name": "杭州宋城",
                "address": "之江路148号",
                "type": "风景名胜;风景名胜;国家级景点",
                "location": "120.096,30.161",
                "suitability_score": 88,
            },
        ]

        merged = merge_to_visit_sites(pois, seed_names={"杭州西湖风景名胜区"}, max_per_site=1)
        names = {p["name"] for p in merged}
        self.assertEqual(len(merged), 2, names)
        self.assertIn("杭州西湖风景名胜区-九溪烟树", names)
        west_lake = next(p for p in merged if p["name"] == "杭州西湖风景名胜区-九溪烟树")
        self.assertIn("雷峰塔景区", west_lake.get("visit_site_members", []))
        self.assertIn("杭州宋城", names)


if __name__ == "__main__":
    unittest.main()
