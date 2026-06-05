"""景点检索查询列表构建。"""

from __future__ import annotations

from typing import Any

from backend.planning.planning_profile import resolve_planning_profile
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.planning.search_strategy import SearchStrategy
from backend.tools.grounding_tools import preferred_tags


def query_types_for_text(query: str) -> str:
    text = str(query or "").strip()
    if any(token in text for token in ("博物馆", "纪念馆", "历史文化街区", "古城", "古镇", "寺", "阁", "故居", "公园", "湖", "山")):
        return ""
    if any(token in text for token in ("景点", "景区", "风景", "地标", "名胜")):
        return "110000"
    return ""


def build_poi_queries(
    destination: str,
    persona: dict[str, Any],
    query_hint: str,
    strategy: SearchStrategy,
    policy: PoiRetrievalPolicy,
) -> list[str]:
    preferred = preferred_tags(persona)
    planning_profile = resolve_planning_profile(
        persona,
        is_wide_area=policy.is_wide_area,
        seed_count=len(policy.seed_name_set()),
    )
    max_queries = max(6, int(policy.max_query_count or 14), planning_profile.query_budget)
    deduped: list[str] = []
    seen: set[str] = set()

    def append_many(items: list[str]) -> None:
        for query in items:
            text = str(query or "").strip()
            if not text or text in seen or len(deduped) >= max_queries:
                continue
            seen.add(text)
            deduped.append(text)

    def initial_seed_queries() -> list[str]:
        seeds = [str(seed).strip() for seed in strategy.seed_poi_names if str(seed).strip()]
        if len(seeds) <= 4:
            return seeds
        if policy.is_wide_area:
            budget = 6
        elif strategy.style_key == "cultural":
            budget = 3
        elif strategy.style_key == "classic":
            budget = 4
        else:
            budget = 4
        return seeds[: min(len(seeds), budget)]

    # 第一轮：先用风格语义主查询打开候选面，避免精确热点词过早吃满预算。
    semantic_hint = str(query_hint or strategy.planner_query_hint or "").strip()
    if semantic_hint:
        append_many([semantic_hint if destination in semantic_hint else f"{destination}{semantic_hint}"])

    # 第二轮：补上目的地语义查询。
    append_many(strategy.build_destination_queries(destination))

    # 第三轮：精确热点词只保留首批代表项，其余交给后续补覆盖流程。
    append_many(initial_seed_queries())

    # 第四轮：用泛关键词和优先级规则继续补强。
    append_many(
        [
            keyword if destination in keyword else f"{destination}{keyword}"
            for keyword in strategy.preferred_keywords[:6]
        ]
    )
    for tag in ("history_culture", "museum", "city_landmark", "nature"):
        if tag in preferred:
            append_many(list(policy.priority_rules.get(tag, [])))

    # 第五轮：如仍有查询预算，再补热点词变体提升命中率。
    direct_queries = strategy.build_direct_queries()
    exact_seed_set = {str(seed).strip() for seed in strategy.seed_poi_names if str(seed).strip()}
    append_many([query for query in direct_queries if str(query).strip() not in exact_seed_set])

    return deduped
