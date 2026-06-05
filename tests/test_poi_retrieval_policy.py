"""景点检索策略与过滤管道测试（不触发高德调用）。"""

from __future__ import annotations

import unittest

from backend.planning.destination_constraints import resolve_constraint_profile
from backend.planning.poi_retrieval.filters import (
    FilterContext,
    NormalizedPoiDraft,
    WideAreaScopeFilter,
    CityLocalProximityFilter,
    WideAreaMuseumFilter,
    apply_filter_chain,
)
from backend.planning.poi_retrieval.normalizer import normalize_pois
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy, SPATIAL_WIDE_AREA, SPATIAL_CITY_LOCAL
from backend.planning.search_strategy import build_search_strategy


class _StaticCoords:
    def should_resolve_search_coordinate(self, row, name, address):  # type: ignore[no-untyped-def]
        return False

    def resolve_poi_coordinate(self, row, detail, destination):  # type: ignore[no-untyped-def]
        return str(row.get("location", ""))


class PoiRetrievalPolicyTests(unittest.TestCase):
    def test_wide_area_policy_from_scenic_strategy(self) -> None:
        strategy = build_search_strategy("川西", "经典热门", scope={"province": "四川省"})
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        self.assertEqual(policy.spatial_mode, SPATIAL_WIDE_AREA)
        self.assertGreater(policy.search_radius_km, 200)

    def test_city_policy_from_city_strategy(self) -> None:
        strategy = build_search_strategy("杭州", "经典热门", scope={"city": "杭州市"})
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        self.assertEqual(policy.spatial_mode, SPATIAL_CITY_LOCAL)
        self.assertTrue(policy.restrict_to_single_city)

    def test_city_scope_rejects_same_province_far_remote_poi(self) -> None:
        strategy = build_search_strategy("乌鲁木齐", "经典热门", scope={"city": "乌鲁木齐市", "province": "新疆维吾尔自治区"})
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        ctx = FilterContext(
            destination="乌鲁木齐",
            policy=policy,
            scope={"city": "乌鲁木齐市", "province": "新疆维吾尔自治区"},
            persona={"travel_style": "经典热门"},
            preferred_tags=set(),
            niche_mode=False,
            constraint_profile=resolve_constraint_profile(
                "乌鲁木齐",
                {"travel_style": "经典热门"},
                {"city": "乌鲁木齐市", "province": "新疆维吾尔自治区"},
            ),
        )
        draft = NormalizedPoiDraft(
            name="昭苏湿地公园",
            type_text="风景名胜;湿地公园",
            poi={
                "name": "昭苏湿地公园",
                "province": "新疆维吾尔自治区",
                "city": "伊犁哈萨克自治州",
                "district": "昭苏县",
                "address": "新疆伊犁昭苏县",
                "distance_to_destination_km": 820,
            },
            tags={"nature"},
            distance_km=820.0,
            knowledge_seed=False,
        )
        self.assertFalse(apply_filter_chain(ctx, draft, [CityLocalProximityFilter()]))
        self.assertFalse(ctx.constraint_profile.poi_in_scope(draft.poi))

    def test_cultural_style_allows_wide_area_museums(self) -> None:
        strategy = build_search_strategy("川西", "文化深度游", scope={"province": "四川省"})
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        self.assertTrue(policy.allow_wide_area_museums)

    def test_seed_passes_scope_filter_without_admin_fields(self) -> None:
        strategy = build_search_strategy(
            "川西",
            "经典热门",
            scope={"destination_aliases": {"四川", "川西"}},
        )
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        ctx = FilterContext(
            destination="川西",
            policy=policy,
            scope={"destination_aliases": {"四川", "川西"}},
            persona={"travel_style": "经典热门"},
            preferred_tags=set(),
            niche_mode=False,
            constraint_profile=resolve_constraint_profile("川西", {"travel_style": "经典热门"}),
        )
        draft = NormalizedPoiDraft(
            name="稻城亚丁风景名胜区",
            type_text="风景名胜",
            poi={
                "name": "稻城亚丁风景名胜区",
                "province": "",
                "city": "甘孜藏族自治州",
                "district": "",
                "address": "",
                "knowledge_seed": True,
            },
            tags=set(),
            distance_km=213.0,
            knowledge_seed=True,
        )
        self.assertTrue(
            apply_filter_chain(ctx, draft, [WideAreaScopeFilter(), CityLocalProximityFilter(), WideAreaMuseumFilter()])
        )

    def test_non_seed_out_of_scope_rejected(self) -> None:
        strategy = build_search_strategy(
            "川西",
            "经典热门",
            scope={"destination_aliases": {"四川", "川西"}},
        )
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        ctx = FilterContext(
            destination="川西",
            policy=policy,
            scope={"destination_aliases": {"四川", "川西"}},
            persona={},
            preferred_tags=set(),
            niche_mode=False,
            constraint_profile=resolve_constraint_profile("川西", {}),
        )
        draft = NormalizedPoiDraft(
            name="某外省景点",
            type_text="风景名胜",
            poi={"name": "某外省景点", "province": "陕西省", "city": "渭南市", "address": "陕西", "knowledge_seed": False},
            tags=set(),
            distance_km=50.0,
            knowledge_seed=False,
        )
        self.assertFalse(apply_filter_chain(ctx, draft, [WideAreaScopeFilter()]))

    def test_wide_area_filter_accepts_cityless_candidate_by_distance(self) -> None:
        strategy = build_search_strategy("西藏", "经典热门", scope={"province": "西藏自治区", "is_province_level": True})
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        ctx = FilterContext(
            destination="西藏",
            policy=policy,
            scope={"destination_aliases": {"西藏", "西藏自治区"}, "is_province_level": True},
            persona={"travel_style": "经典热门"},
            preferred_tags=set(),
            niche_mode=False,
            constraint_profile=resolve_constraint_profile("西藏", {"travel_style": "经典热门"}),
        )
        draft = NormalizedPoiDraft(
            name="布达拉宫",
            type_text="风景名胜",
            poi={
                "name": "布达拉宫",
                "province": "",
                "city": "",
                "district": "",
                "address": "",
                "distance_to_destination_km": 0.8,
            },
            tags={"history_culture", "city_landmark"},
            distance_km=0.8,
            knowledge_seed=False,
        )
        self.assertTrue(apply_filter_chain(ctx, draft, [WideAreaScopeFilter()]))

    def test_wide_area_museum_allowed_when_seed_coverage_missing(self) -> None:
        strategy = build_search_strategy("西藏", "经典热门", scope={"province": "西藏自治区", "is_province_level": True})
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        ctx = FilterContext(
            destination="西藏",
            policy=policy,
            scope={"destination_aliases": {"西藏", "西藏自治区"}, "is_province_level": True},
            persona={"travel_style": "经典热门"},
            preferred_tags=set(),
            niche_mode=False,
            constraint_profile=resolve_constraint_profile("西藏", {"travel_style": "经典热门"}),
        )
        draft = NormalizedPoiDraft(
            name="西藏博物馆",
            type_text="科教文化服务;博物馆;博物馆",
            poi={
                "name": "西藏博物馆",
                "province": "西藏自治区",
                "city": "拉萨市",
                "district": "",
                "address": "罗布林卡路34号",
                "distance_to_destination_km": 1.6,
            },
            tags={"museum", "history_culture"},
            distance_km=1.6,
            knowledge_seed=False,
        )
        self.assertTrue(apply_filter_chain(ctx, draft, [WideAreaScopeFilter(), CityLocalProximityFilter()]))

    def test_normalize_wide_area_keeps_cityless_tibet_poi_and_drops_remote_noise(self) -> None:
        strategy = build_search_strategy("西藏", "经典热门", scope={"province": "西藏自治区", "is_province_level": True})
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        rows = [
            {
                "id": "potala",
                "name": "布达拉宫",
                "location": "91.117,29.657",
                "type": "风景名胜;风景名胜",
                "pname": "",
                "cityname": "",
                "adname": "",
                "address": "",
            },
            {
                "id": "road-store",
                "name": "1点点(西藏南路店)",
                "location": "121.486723,31.208854",
                "type": "餐饮服务;冷饮店;冷饮店",
                "pname": "",
                "cityname": "",
                "adname": "",
                "address": "上海市黄浦区西藏南路",
            },
        ]
        pois = normalize_pois(
            rows,
            "91.117,29.657",
            "西藏",
            {"travel_style": "经典热门", "destination_region_type": "province"},
            {"province": "西藏自治区", "is_province_level": True, "destination_aliases": {"西藏", "西藏自治区"}},
            policy,
            _StaticCoords(),
        )
        names = [poi["name"] for poi in pois]
        self.assertIn("布达拉宫", names)
        self.assertNotIn("1点点(西藏南路店)", names)


if __name__ == "__main__":
    unittest.main()
