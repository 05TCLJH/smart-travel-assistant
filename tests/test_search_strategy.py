"""检索策略引擎：风格 × 目的地类型矩阵（不调用高德）。"""

from __future__ import annotations

import unittest

from backend.planning.search_strategy import STYLE_KEYS, build_search_strategy, normalize_style_key
from backend.services.persona_service import PersonaService
from backend.tools.amap_tools import TravelResearchTools


STYLE_LABELS = {
    "classic": "经典热门",
    "offbeat": "小众探索",
    "leisure": "休闲度假",
    "adventure": "户外探险",
    "cultural": "文化深度游",
}


class SearchStrategyMatrixTests(unittest.TestCase):
    def test_all_frontend_styles_map_to_keys(self) -> None:
        for label in STYLE_LABELS.values():
            self.assertIn(normalize_style_key(label), STYLE_KEYS)

    def test_city_classic_uses_city_filters(self) -> None:
        s = build_search_strategy("南京", "经典热门", scope={"city": "南京市", "province": "江苏省"})
        self.assertEqual(s.destination_kind, "city")
        self.assertTrue(s.apply_city_museum_filters)
        self.assertTrue(s.restrict_to_single_city)
        self.assertLess(s.search_radius_km, 100)

    def test_city_cultural_keywords(self) -> None:
        s = build_search_strategy("西安", "文化深度游", scope={"city": "西安市"})
        self.assertIn("museum", s.interests)
        self.assertTrue(any("博物馆" in k for k in s.query_suffixes))

    def test_scenic_region_inferred_without_catalog(self) -> None:
        s = build_search_strategy("川西", "户外探险", scope={"city": "阿坝藏族羌族自治州"})
        self.assertEqual(s.destination_kind, "scenic_region")
        self.assertFalse(s.restrict_to_single_city)
        self.assertGreater(s.search_radius_km, 200)
        self.assertFalse(s.apply_city_museum_filters)

    def test_offbeat_scenic_suffixes(self) -> None:
        s = build_search_strategy("呼伦贝尔", "小众探索", scope={"city": "呼伦贝尔市"})
        self.assertEqual(s.style_key, "offbeat")
        joined = " ".join(s.query_suffixes)
        self.assertTrue(any(token in joined for token in ("小众", "秘境", "草原")))

    def test_ili_curated_seeds_only_enhance(self) -> None:
        s = build_search_strategy("伊犁", "经典热门", scope={"city": "伊犁哈萨克自治州", "province": "新疆"})
        self.assertEqual(s.destination_kind, "scenic_region")
        self.assertTrue(any("赛里木湖" in q for q in s.build_direct_queries()))
        self.assertIn("nature", s.interests)

    def test_unknown_city_still_produces_queries(self) -> None:
        s = build_search_strategy("莆田", "经典热门", scope={"city": "莆田市", "province": "福建省"})
        queries = s.build_destination_queries("莆田")
        self.assertGreaterEqual(len(queries), 3)

    def test_persona_enrich_attaches_strategy(self) -> None:
        persona = PersonaService().enrich(
            {"travel_style": "休闲度假"},
            {"destination": "杭州", "days": 3, "budget": 5000},
        )
        self.assertEqual(persona.get("style_key"), "leisure")
        self.assertIn("search_strategy", persona)
        self.assertIn("destination_region_type", persona)

    def test_amap_query_builder_uses_strategy(self) -> None:
        tools = TravelResearchTools()
        persona = PersonaService().enrich(
            {"travel_style": "文化深度游"},
            {"destination": "洛阳", "days": 3, "budget": 4000},
        )
        scope = {"city": "洛阳市", "province": "河南省", "destination_aliases": {"洛阳", "河南"}}
        strategy = build_search_strategy("洛阳", persona["travel_style"], scope)
        queries = tools._build_poi_queries("洛阳", persona, "", scope, strategy)
        self.assertTrue(any("博物馆" in q or "古迹" in q for q in queries))

    def test_curated_city_queries_reserve_budget_for_semantic_search(self) -> None:
        s = build_search_strategy("青岛", "经典热门", scope={"city": "青岛市", "province": "山东省"})
        queries = s.seed_poi_names[:]
        self.assertGreaterEqual(len(queries), 8)

        built = TravelResearchTools()._build_poi_queries(
            "青岛",
            {"travel_style": "经典热门"},
            "热门景点",
            {"city": "青岛市", "province": "山东省", "destination_aliases": {"青岛", "山东"}},
            s,
        )
        self.assertIn("青岛热门景点", built)
        self.assertIn("青岛必去景点", built)
        seed_hits = [seed for seed in s.seed_poi_names if seed in built]
        self.assertGreaterEqual(len(seed_hits), 3)
        self.assertLess(len(seed_hits), len(s.seed_poi_names))


if __name__ == "__main__":
    unittest.main()
