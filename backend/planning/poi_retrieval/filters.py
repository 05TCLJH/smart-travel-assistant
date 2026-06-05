"""景点归一化过滤管道：策略驱动、可组合、无目的地硬编码。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from backend.planning.destination_constraints import DestinationConstraintProfile
from backend.planning.poi_roles import is_itinerary_eligible_role, resolve_poi_role
from backend.planning.poi_retrieval.classifiers import MUSEUM_NAME_TOKENS, is_complex_sub_poi, is_food_poi_type
from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.tools.grounding_tools import (
    is_auxiliary_poi,
    is_generic_urban_poi,
    is_secondary_poi,
    normalize_poi_tags,
    preferred_tags,
)


class FilterDecision(Enum):
    ACCEPT = "accept"
    REJECT = "reject"


@dataclass
class NormalizedPoiDraft:
    """归一化过程中的 POI 草稿，供过滤器链评估。"""

    name: str
    type_text: str
    poi: dict[str, Any]
    tags: set[str]
    distance_km: float
    knowledge_seed: bool


@dataclass(frozen=True)
class FilterContext:
    destination: str
    policy: PoiRetrievalPolicy
    scope: dict[str, Any]
    persona: dict[str, Any]
    preferred_tags: set[str]
    niche_mode: bool
    constraint_profile: DestinationConstraintProfile


class PoiFilter(Protocol):
    def evaluate(self, ctx: FilterContext, draft: NormalizedPoiDraft) -> FilterDecision: ...


class WideAreaScopeFilter:
    """大区检索：统一交给地理约束规则判断范围，避免采集层和归一化层各有一套口径。"""

    def evaluate(self, ctx: FilterContext, draft: NormalizedPoiDraft) -> FilterDecision:
        if not ctx.policy.is_wide_area:
            return FilterDecision.ACCEPT
        if ctx.constraint_profile.poi_in_scope(draft.poi):
            return FilterDecision.ACCEPT
        return FilterDecision.REJECT


class CityLocalProximityFilter:
    """城市检索：POI 所在城与目的地不一致且距离锚点过远时剔除。"""

    def evaluate(self, ctx: FilterContext, draft: NormalizedPoiDraft) -> FilterDecision:
        if ctx.policy.is_wide_area:
            return FilterDecision.ACCEPT
        if draft.knowledge_seed:
            return FilterDecision.ACCEPT
        seeds = ctx.policy.seed_name_set()
        if seeds and any(seed in draft.name or draft.name in seed for seed in seeds):
            return FilterDecision.ACCEPT
        city = str(draft.poi.get("city", "")).strip()
        if not city:
            return FilterDecision.ACCEPT
        destination = ctx.destination
        if destination in city or destination in str(draft.poi.get("district", "")).strip():
            return FilterDecision.ACCEPT
        if draft.distance_km <= ctx.policy.city_local_max_distance_km:
            return FilterDecision.ACCEPT
        return FilterDecision.REJECT


class AuxiliaryPoiFilter:
    def evaluate(self, ctx: FilterContext, draft: NormalizedPoiDraft) -> FilterDecision:
        if is_auxiliary_poi(draft.poi) or is_secondary_poi(draft.poi):
            return FilterDecision.REJECT
        return FilterDecision.ACCEPT


class ItineraryRoleFilter:
    """仅保留可进入行程主线的 POI 角色（零售/餐饮/附属等由 poi_roles 统一剔除）。"""

    def evaluate(self, ctx: FilterContext, draft: NormalizedPoiDraft) -> FilterDecision:
        role = resolve_poi_role(draft.poi)
        if is_itinerary_eligible_role(role):
            return FilterDecision.ACCEPT
        return FilterDecision.REJECT


class WideAreaMuseumFilter:
    """环线经典/休闲等：仅保留知识库种子名单内的博物馆类 POI。"""

    def evaluate(self, ctx: FilterContext, draft: NormalizedPoiDraft) -> FilterDecision:
        if not ctx.policy.is_wide_area:
            return FilterDecision.ACCEPT
        if ctx.policy.allow_wide_area_museums:
            return FilterDecision.ACCEPT
        if not any(token in draft.name for token in MUSEUM_NAME_TOKENS):
            return FilterDecision.ACCEPT
        seeds = ctx.policy.seed_name_set()
        if not seeds:
            return FilterDecision.ACCEPT
        if any(seed and (seed in draft.name or draft.name in seed) for seed in seeds):
            return FilterDecision.ACCEPT
        return FilterDecision.REJECT


class CityMuseumQualityFilter:
    """城市 + 文化偏好：专题馆、低评分馆、泛城市广场等质量过滤。"""

    LOW_QUALITY_MUSEUM_TOKENS = (
        "消防",
        "地质",
        "钱币",
        "老酒",
        "巧克力",
        "VR",
        "专题",
        "社区",
        "驿站",
        "书画",
        "昆虫",
        "藏品",
        "航天",
        "保护中心",
        "研究中心",
        "附属医院",
        "医科大学",
    )

    def evaluate(self, ctx: FilterContext, draft: NormalizedPoiDraft) -> FilterDecision:
        if not ctx.policy.apply_city_museum_filters:
            return FilterDecision.ACCEPT
        preferred = ctx.preferred_tags
        if not (preferred & {"history_culture", "museum"}):
            return FilterDecision.ACCEPT
        if ctx.niche_mode:
            from backend.planning.style_affinity import NICHE_LOW_VALUE_MUSEUM, OFFBEAT_POSITIVE

            if any(token in draft.name for token in NICHE_LOW_VALUE_MUSEUM):
                return FilterDecision.REJECT
            if any(token in draft.name for token in OFFBEAT_POSITIVE):
                return FilterDecision.ACCEPT
            if "博物馆" in draft.name and any(token in draft.name for token in ("艺术", "创意", "街头", "街区")):
                return FilterDecision.ACCEPT
        if "city_landmark" not in preferred and is_generic_urban_poi(draft.poi):
            if not (draft.tags & {"history_culture", "museum", "street"}):
                return FilterDecision.REJECT
        if any(token in draft.name for token in self.LOW_QUALITY_MUSEUM_TOKENS):
            return FilterDecision.REJECT
        rating_raw = draft.poi.get("rating", "")
        try:
            rating_value = float(rating_raw)
        except (TypeError, ValueError):
            rating_value = 0.0
        if rating_value and rating_value < 4.0 and "city_landmark" not in draft.tags:
            return FilterDecision.REJECT
        return FilterDecision.ACCEPT


def build_normalization_filters() -> list[PoiFilter]:
    """过滤器顺序固定；新增规则应实现 PoiFilter 并在此注册。"""
    return [
        WideAreaScopeFilter(),
        CityLocalProximityFilter(),
        ItineraryRoleFilter(),
        AuxiliaryPoiFilter(),
        WideAreaMuseumFilter(),
        CityMuseumQualityFilter(),
    ]


def apply_filter_chain(ctx: FilterContext, draft: NormalizedPoiDraft, filters: list[PoiFilter] | None = None) -> bool:
    chain = filters or build_normalization_filters()
    for poi_filter in chain:
        if poi_filter.evaluate(ctx, draft) == FilterDecision.REJECT:
            return False
    return True
