"""五种旅行风格：候选池规模 + 头部类型是否符合预期。"""

from __future__ import annotations

import unittest

from backend.planning.search_strategy import STYLE_BASE, build_search_strategy, merge_strategy_into_persona
from backend.planning.style_affinity import rank_by_style_affinity, select_planning_pool
from backend.tools.grounding_tools import guard_candidate_pois, strict_style_mode
from backend.tools.planning_tools import rank_candidates

# 模拟一座城市高德混合召回（武汉型）
MIXED_CITY_CANDIDATES = [
    {"name": "黄鹤楼", "type": "风景名胜;国家级景点", "popularity_score": 92},
    {"name": "湖北省博物馆", "type": "博物馆", "popularity_score": 88},
    {"name": "东湖绿道", "type": "公园;风景名胜", "popularity_score": 75},
    {"name": "江汉路步行街", "type": "步行街", "popularity_score": 78},
    {"name": "昙华林历史文化街区", "type": "历史文化街区", "popularity_score": 70},
    {"name": "武汉警察博物馆", "type": "博物馆", "popularity_score": 55},
    {"name": "黎黄陂路街头博物馆", "type": "科教文化;博物馆", "popularity_score": 62},
    {"name": "木兰天池", "type": "风景名胜;景区", "popularity_score": 72},
    {"name": "武汉大学", "type": "风景名胜", "popularity_score": 80},
    {"name": "汉口江滩", "type": "公园广场", "popularity_score": 76},
    {"name": "武汉科技馆", "type": "科技馆", "popularity_score": 65},
    {"name": "归元禅寺", "type": "寺庙", "popularity_score": 68},
    {"name": "403国际艺术中心", "type": "艺术场馆", "popularity_score": 58},
    {"name": "武汉海昌极地海洋公园", "type": "主题公园", "popularity_score": 70},
    {"name": "光谷步行街", "type": "步行街", "popularity_score": 74},
]

STYLE_LABELS = {
    "classic": "经典热门",
    "offbeat": "小众探索",
    "leisure": "休闲度假",
    "adventure": "户外探险",
    "cultural": "文化深度游",
}

DAYS = 3
MIN_POOL = 8  # 守卫层按天数乘三预留最小候选池


def _persona(style_key: str) -> dict:
    label = STYLE_LABELS[style_key]
    strategy = build_search_strategy("武汉", label, scope={"city": "武汉市", "province": "湖北省"})
    base = STYLE_BASE[style_key]
    return merge_strategy_into_persona(
        {
            "travel_style": label,
            "likes": list(base.get("preferred_keywords", []))[:2],
            "stamina": "充沛",
        },
        strategy,
    )


def _top_names(pool: list[dict], n: int = 5) -> list[str]:
    return [str(p.get("name", "")) for p in pool[:n]]


class StyleAffinityMatrixTests(unittest.TestCase):
    def test_all_styles_have_search_queries(self) -> None:
        for key, label in STYLE_LABELS.items():
            s = build_search_strategy("武汉", label, scope={"city": "武汉市"})
            queries = s.build_destination_queries("武汉") + s.build_direct_queries()
            self.assertGreaterEqual(len(queries), 3, key)

    def test_guard_keeps_enough_for_each_style(self) -> None:
        request = {"destination": "武汉", "days": DAYS}
        for key in STYLE_LABELS:
            persona = _persona(key)
            ranked = rank_candidates(MIXED_CITY_CANDIDATES, persona, {})
            kept, guard = guard_candidate_pois(ranked, request, persona, {})
            self.assertGreaterEqual(
                guard["kept_count"],
                MIN_POOL,
                f"{key} kept={guard['kept_count']} strict={guard['strict_mode']}",
            )

    def test_planning_pool_enough_for_each_style(self) -> None:
        for key in STYLE_LABELS:
            persona = _persona(key)
            ranked = rank_candidates(MIXED_CITY_CANDIDATES, persona, {})
            pool = select_planning_pool(
                ranked,
                persona,
                required_total=DAYS * 4,
                days=DAYS,
                strict_style=strict_style_mode(persona),
            )
            self.assertGreaterEqual(len(pool), 6, f"{key} pool={len(pool)}")

    def test_classic_prefers_landmarks(self) -> None:
        persona = _persona("classic")
        pool = select_planning_pool(
            rank_candidates(MIXED_CITY_CANDIDATES, persona, {}),
            persona,
            required_total=12,
            days=DAYS,
            strict_style=True,
        )
        top = " ".join(_top_names(pool, 6))
        self.assertTrue(any(x in top for x in ("黄鹤楼", "湖北省博物馆", "武汉大学")), top)

    def test_cultural_prefers_museums(self) -> None:
        persona = _persona("cultural")
        ranked = rank_by_style_affinity(rank_candidates(MIXED_CITY_CANDIDATES, persona, {}), persona)
        top = " ".join(_top_names(ranked, 5))
        self.assertIn("博物馆", top)

    def test_adventure_prefers_nature(self) -> None:
        persona = _persona("adventure")
        ranked = rank_by_style_affinity(rank_candidates(MIXED_CITY_CANDIDATES, persona, {}), persona)
        top = " ".join(_top_names(ranked, 4))
        self.assertTrue(any(x in top for x in ("东湖", "木兰", "绿道", "天池")), top)

    def test_offbeat_excludes_police_museum(self) -> None:
        persona = _persona("offbeat")
        pool = select_planning_pool(
            rank_candidates(MIXED_CITY_CANDIDATES, persona, {}),
            persona,
            required_total=12,
            days=DAYS,
            strict_style=True,
        )
        names = {p["name"] for p in pool}
        self.assertNotIn("武汉警察博物馆", names)
        self.assertGreaterEqual(len(names), 5)


if __name__ == "__main__":
    unittest.main()
