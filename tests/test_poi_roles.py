"""景点角色与景区簇架构测试。"""

from __future__ import annotations

import unittest

from backend.planning.poi_roles import PoiRole, classify_poi_role, is_itinerary_eligible_role
from backend.planning.scenic_clusters import dedupe_by_scenic_cluster, scenic_cluster_key


class PoiRoleTests(unittest.TestCase):
    def test_retail_typecode_not_itinerary(self) -> None:
        role = classify_poi_role("海澜之家(解放碑步行街店)", "购物服务;服装鞋帽皮具;品牌服装店")
        self.assertEqual(role, PoiRole.RETAIL)
        self.assertFalse(is_itinerary_eligible_role(role))

    def test_scenic_remains_itinerary(self) -> None:
        role = classify_poi_role("洪崖洞民俗风貌区", "风景名胜;风景名胜;风景名胜")
        self.assertEqual(role, PoiRole.SCENIC)
        self.assertTrue(is_itinerary_eligible_role(role))

    def test_retail_not_merged_into_jiefangbei_cluster(self) -> None:
        seeds = {"解放碑步行街", "洪崖洞民俗风貌区"}
        retail = {"name": "海澜之家(解放碑步行街店)", "type": "购物服务;品牌服装店", "poi_role": "retail"}
        scenic = {"name": "洪崖洞民俗风貌区", "type": "风景名胜", "poi_role": "scenic", "popularity_score": 90}
        key_retail = scenic_cluster_key(retail["name"], seeds, poi=retail)
        key_scenic = scenic_cluster_key(scenic["name"], seeds, poi=scenic)
        self.assertEqual(key_retail, "")
        self.assertNotEqual(key_scenic, "")

    def test_dedupe_drops_retail_keeps_scenic(self) -> None:
        pois = [
            {"name": "海澜之家(解放碑步行街店)", "type": "购物服务", "poi_role": "retail", "popularity_score": 99},
            {"name": "洪崖洞民俗风貌区", "type": "风景名胜", "poi_role": "scenic", "popularity_score": 80},
            {"name": "解放碑步行街", "type": "风景名胜", "poi_role": "street_landmark", "popularity_score": 70},
        ]
        out = dedupe_by_scenic_cluster(pois, seed_names={"解放碑步行街", "洪崖洞民俗风貌区"})
        names = {p["name"] for p in out}
        self.assertNotIn("海澜之家(解放碑步行街店)", names)
        self.assertIn("洪崖洞民俗风貌区", names)

    def test_parenthetical_only_for_landmark_roles(self) -> None:
        seeds = {"宽窄巷子"}
        street_poi = {"name": "长城雪茄(宽窄巷子店)", "type": "风景名胜", "poi_role": "street_landmark"}
        retail_poi = {"name": "某某专卖(宽窄巷子店)", "type": "购物服务", "poi_role": "retail"}
        self.assertEqual(
            scenic_cluster_key("宽窄巷子东广场", seeds, poi=street_poi),
            scenic_cluster_key(street_poi["name"], seeds, poi=street_poi),
        )
        self.assertEqual(scenic_cluster_key(retail_poi["name"], seeds, poi=retail_poi), "")


if __name__ == "__main__":
    unittest.main()
