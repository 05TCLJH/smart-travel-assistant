"""川西环线：地理编码锚点与行政区冲突判断。"""

from __future__ import annotations

import unittest

from backend.knowledge.destination_catalog import _load_catalog, resolve_geocode_query
from backend.planning.poi_retrieval import normalize_pois
from backend.planning.poi_retrieval.pipeline import AmapCoordinateResolver
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.planning.search_strategy import build_search_strategy
from backend.tools.amap_tools import TravelResearchTools
from backend.tools.grounding_tools import destination_conflict


class ChuanxiGroundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _load_catalog.cache_clear()

    def test_geocode_anchor_not_raw_chuanxi(self) -> None:
        anchor = resolve_geocode_query("川西")
        self.assertIn("四川", anchor)
        self.assertNotEqual(anchor, "川西")

    def test_sichuan_poi_not_conflict(self) -> None:
        poi = {
            "name": "稻城亚丁风景名胜区",
            "city": "稻城县",
            "province": "四川省",
            "address": "四川省甘孜藏族自治州稻城县",
        }
        self.assertFalse(destination_conflict(poi, "川西"))

    def test_shaanxi_poi_still_conflict(self) -> None:
        poi = {"name": "某景点", "city": "渭南市", "province": "陕西省", "address": "陕西"}
        self.assertTrue(destination_conflict(poi, "川西"))

    def test_wide_area_seed_kept_when_city_differs(self) -> None:
        tools = TravelResearchTools()
        scope = {
            "province": "四川省",
            "city": "甘孜藏族自治州",
            "is_scenic_region": True,
            "destination_aliases": {"四川", "甘孜", "阿坝", "川西"},
        }
        strategy = build_search_strategy("川西", "经典热门", scope)
        origin = "101.956870,29.998544"
        rows = [
            {
                "name": "稻城亚丁风景名胜区",
                "location": "100.298000,27.826000",
                "type": "风景名胜;风景名胜",
                "cityname": "甘孜藏族自治州",
                "pname": "四川省",
                "adname": "稻城县",
                "address": "四川省甘孜藏族自治州稻城县",
                "_knowledge_seed": True,
            }
        ]
        persona = {"travel_style": "经典热门", "destination_region_type": "scenic_region"}
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        pois = normalize_pois(rows, origin, "川西", persona, scope, policy, AmapCoordinateResolver(tools))
        self.assertEqual(len(pois), 1)
        self.assertIn("稻城", pois[0]["name"])


if __name__ == "__main__":
    unittest.main()
