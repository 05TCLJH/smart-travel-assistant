"""大区检索：采集结果须覆盖多个检索词，而非被单一热点占满。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.planning.poi_retrieval.collector import (
    collect_candidate_rows,
    diversify_collected_rows,
    select_rows_for_enrichment,
)
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.planning.search_strategy import SearchStrategy


def _wide_policy() -> PoiRetrievalPolicy:
    strategy = SearchStrategy(
        style_key="classic",
        destination_kind="scenic_region",
        destination="伊犁",
        wide_area_search=True,
        search_radius_km=420,
        restrict_to_single_city=False,
        seed_poi_names=["赛里木湖", "那拉提草原", "喀拉峻草原"],
    )
    return PoiRetrievalPolicy.from_strategy(strategy)


class PoiCollectorDiversityTests(unittest.TestCase):
    def test_diversify_round_robin_queries(self) -> None:
        rows = []
        for query in ("赛里木湖", "那拉提草原", "喀拉峻草原"):
            for idx in range(4):
                rows.append({"id": f"{query}-{idx}", "name": f"{query}-{idx}", "_query": query})
        policy = _wide_policy()
        out = diversify_collected_rows(rows, policy, max_total=9, per_query_cap=3)
        queries = {str(row.get("_query")) for row in out}
        self.assertGreaterEqual(len(queries), 3)
        self.assertLessEqual(len(out), 9)

    def test_collect_stops_global_flood_from_first_query(self) -> None:
        policy = _wide_policy()
        amap = MagicMock()

        def fake_search(query: str, **kwargs):
            return {"pois": [{"id": f"{query}-1", "name": f"{query}-景点", "location": "81.0,43.0"}]}

        amap.text_search.side_effect = fake_search
        scope = {"destination_aliases": {"伊犁", "新疆"}}
        rows = collect_candidate_rows(
            amap,
            "伊犁",
            scope,
            ["赛里木湖", "那拉提草原", "喀拉峻草原"],
            policy,
            priority_score_fn=lambda _poi: 1.0,
        )
        queries = {str(row.get("_query")) for row in rows}
        self.assertEqual(queries, {"赛里木湖", "那拉提草原", "喀拉峻草原"})

    def test_collect_wide_area_keeps_cityless_scenic_rows_for_downstream_geo_filter(self) -> None:
        policy = _wide_policy()
        amap = MagicMock()
        amap.text_search.return_value = {
            "pois": [
                {"id": "tibet-1", "name": "布达拉宫", "type": "风景名胜", "location": "91.117,29.657"},
                {"id": "road-1", "name": "1点点(西藏南路店)", "type": "餐饮服务", "location": "121.486,31.208"},
            ]
        }
        scope = {"destination_aliases": {"西藏", "西藏自治区"}, "is_province_level": True}
        rows = collect_candidate_rows(
            amap,
            "西藏",
            scope,
            ["西藏热门景点"],
            policy,
            priority_score_fn=lambda _poi: 1.0,
        )
        names = [str(row.get("name")) for row in rows]
        self.assertIn("布达拉宫", names)

    def test_enrichment_selection_preserves_seed_coverage(self) -> None:
        strategy = SearchStrategy(
            style_key="classic",
            destination_kind="city",
            destination="青岛",
            wide_area_search=False,
            search_radius_km=35,
            restrict_to_single_city=True,
            seed_poi_names=["栈桥", "八大关风景区", "崂山风景名胜区", "五四广场"],
        )
        policy = PoiRetrievalPolicy.from_strategy(strategy)
        rows = [
            {"id": f"bridge-{idx}", "name": f"栈桥-{idx}", "_query": "栈桥", "_knowledge_seed": True}
            for idx in range(8)
        ]
        rows += [
            {"id": f"bada-{idx}", "name": f"八大关-{idx}", "_query": "八大关风景区", "_knowledge_seed": True}
            for idx in range(6)
        ]
        rows += [
            {"id": "mount-0", "name": "崂山风景区", "_query": "崂山风景名胜区", "_knowledge_seed": True},
            {"id": "square-0", "name": "五四广场", "_query": "五四广场", "_knowledge_seed": True},
        ]

        selected = select_rows_for_enrichment(rows, policy, max_total=6)
        selected_queries = {str(row.get("_query")) for row in selected}
        self.assertIn("栈桥", selected_queries)
        self.assertIn("八大关风景区", selected_queries)
        self.assertIn("崂山风景名胜区", selected_queries)
        self.assertIn("五四广场", selected_queries)


if __name__ == "__main__":
    unittest.main()
