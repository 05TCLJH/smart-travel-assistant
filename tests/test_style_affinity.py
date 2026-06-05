"""风格亲和度：小众探索不应只剩极少数博物馆。"""

from __future__ import annotations

import unittest

from backend.planning.candidate_selection import select_diverse_candidates
from backend.planning.style_affinity import (
    compute_style_affinity,
    hard_style_veto,
    rank_by_style_affinity,
    select_planning_pool,
)
from backend.planning.search_strategy import build_search_strategy, merge_strategy_into_persona
from backend.tools.planning_tools import rank_candidates


def _offbeat_persona() -> dict:
    strategy = build_search_strategy("武汉", "小众探索", scope={"city": "武汉市", "province": "湖北省"})
    return merge_strategy_into_persona(
        {
            "travel_style": "小众探索",
            "likes": ["小众景点", "本地体验"],
            "stamina": "充沛",
        },
        strategy,
    )


class StyleAffinityTests(unittest.TestCase):
    def test_police_museum_vetoed_for_offbeat(self) -> None:
        persona = _offbeat_persona()
        poi = {"name": "武汉警察博物馆", "type": "博物馆", "rating": "4.5"}
        self.assertIsNotNone(hard_style_veto(poi, persona))

    def test_creative_street_museum_ok_for_offbeat(self) -> None:
        persona = _offbeat_persona()
        poi = {"name": "黎黄陂路街头博物馆", "type": "科教文化服务;博物馆", "rating": "4.6"}
        self.assertIsNone(hard_style_veto(poi, persona))
        aff = compute_style_affinity(poi, persona)
        self.assertGreater(aff.score, 55.0)

    def test_old_street_ranks_above_police_museum(self) -> None:
        persona = _offbeat_persona()
        candidates = [
            {"name": "武汉警察博物馆", "type": "博物馆", "popularity_score": 70},
            {"name": "黎黄陂路", "type": "风景名胜;历史文化街区", "popularity_score": 65},
            {"name": "昙华林历史文化街区", "type": "步行街", "popularity_score": 68},
            {"name": "403国际艺术中心", "type": "科教文化", "popularity_score": 60},
            {"name": "江汉路步行街", "type": "步行街", "popularity_score": 72},
        ]
        ranked = rank_by_style_affinity(candidates, persona, min_affinity=0.0)
        names = [p["name"] for p in ranked]
        self.assertNotIn("武汉警察博物馆", names)
        self.assertIn("黎黄陂路", names)

    def test_planning_pool_keeps_multiple_offbeat_types(self) -> None:
        persona = _offbeat_persona()
        ranked = rank_candidates(
            [
                {"name": "武汉警察博物馆", "type": "博物馆"},
                {"name": "黎黄陂路", "type": "历史文化街区"},
                {"name": "昙华林历史文化街区", "type": "步行街"},
                {"name": "403国际艺术中心", "type": "艺术场馆"},
                {"name": "江汉路步行街", "type": "步行街"},
                {"name": "汉阳江滩", "type": "公园"},
            ],
            persona,
            {},
        )
        pool = select_planning_pool(ranked, persona, required_total=6, days=3, strict_style=True)
        self.assertGreaterEqual(len(pool), 4)
        joined = " ".join(p["name"] for p in pool)
        self.assertTrue(any(token in joined for token in ("黎黄陂", "昙华林", "江汉路", "江滩", "403")))

    def test_diverse_selection_keeps_high_affinity_anchor_after_dedupe(self) -> None:
        persona = _offbeat_persona()
        ranked = [
            {
                "name": "创意码头街区",
                "type": "历史文化街区",
                "style_affinity": 86,
                "suitability_score": 82,
                "constraint_score": 80,
                "preference_hit": True,
            },
            {
                "name": "创意码头游客中心",
                "type": "生活服务",
                "style_affinity": 22,
                "suitability_score": 90,
                "constraint_score": 70,
                "preference_hit": False,
            },
            {
                "name": "江岸步道",
                "type": "步行街",
                "style_affinity": 72,
                "suitability_score": 78,
                "constraint_score": 76,
                "preference_hit": True,
            },
        ]
        selected = select_diverse_candidates(ranked, persona, required_total=2, days=2)
        names = [item["name"] for item in selected]
        self.assertIn("创意码头街区", names)
        self.assertNotIn("创意码头游客中心", names)


if __name__ == "__main__":
    unittest.main()
