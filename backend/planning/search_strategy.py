"""检索策略引擎：根据旅行风格与目的地类型生成统一的景点检索、过滤与排序配置。

不依赖某一城市的硬编码；可选目的地知识库仅用于质量增强。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend.knowledge.destination_catalog import (
    curated_hotspots_for_style,
    curated_priority_rules,
    get_curated_profile,
    infer_destination_kind,
)
from backend.tools.grounding_tools import admin_aliases, is_province_level_destination_name


STYLE_KEYS = ("classic", "offbeat", "leisure", "adventure", "cultural")
DESTINATION_KINDS = ("city", "scenic_region", "province")


@dataclass
class SearchStrategy:
    style_key: str
    destination_kind: str
    destination: str
    interests: list[str] = field(default_factory=list)
    preferred_keywords: list[str] = field(default_factory=list)
    preferred_poi_types: list[str] = field(default_factory=list)
    avoid_keywords: list[str] = field(default_factory=list)
    mainstream_preference: float = 0.5
    route_style: str = "compact"
    seed_poi_names: list[str] = field(default_factory=list)
    query_suffixes: list[str] = field(default_factory=list)
    planner_query_hint: str = ""
    search_radius_km: float = 35.0
    wide_area_search: bool = False
    restrict_to_single_city: bool = True
    apply_city_museum_filters: bool = True
    scope_aliases: set[str] = field(default_factory=set)
    priority_rules: dict[str, list[str]] = field(default_factory=dict)
    max_query_count: int = 14

    def to_persona_fields(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scope_aliases"] = sorted(self.scope_aliases)
        payload["destination_region_type"] = self.destination_kind
        payload["destination_hotspots"] = list(self.seed_poi_names)
        return payload

    def build_direct_queries(self) -> list[str]:
        queries: list[str] = []
        for name in self.seed_poi_names[:12]:
            text = str(name).strip()
            if not text:
                continue
            queries.append(text)
            if not any(token in text for token in ("景区", "公园", "草原", "湖", "沟", "街", "大桥", "古道")):
                queries.append(f"{text}景区")
        return queries

    def build_destination_queries(self, destination: str) -> list[str]:
        dest = str(destination or self.destination).strip()
        queries: list[str] = []
        for suffix in self.query_suffixes:
            text = str(suffix).strip()
            if not text:
                continue
            queries.append(text if dest in text else f"{dest}{text}")
        return queries


# ---------- 风格基底（与前端五种旅行风格一一对应）----------

STYLE_BASE: dict[str, dict[str, Any]] = {
    "classic": {
        "interests": ["history_culture", "museum", "city_landmark", "nature"],
        "preferred_poi_types": ["旅游景点", "风景名胜", "博物馆", "历史文化", "古迹"],
        "preferred_keywords": ["热门景点", "必去", "核心景点", "经典线路", "5A景区"],
        "avoid_keywords": ["纯购物", "写字楼", "游客服务中心", "办公楼", "不对外开放"],
        "mainstream_preference": 0.9,
        "route_style": "compact",
        "query_suffixes": ["热门景点", "必去景点", "核心景点", "经典景点"],
        "planner_query_hint": "热门景点 必去 5A景区 地标",
    },
    "offbeat": {
        "interests": ["street", "nature", "history_culture", "niche"],
        "preferred_poi_types": ["历史文化街区", "老街", "步道", "创意园区", "小众景点"],
        "preferred_keywords": ["小众景点", "本地人爱去", "冷门", "老街", "步道", "创意园", "市集"],
        "avoid_keywords": ["必去", "城市地标", "网红打卡", "游客中心", "经典线路"],
        "mainstream_preference": 0.12,
        "route_style": "discovery",
        "query_suffixes": ["小众景点", "本地人爱去", "老街", "步道", "创意园"],
        "planner_query_hint": "小众景点 本地人爱去 老街 步道",
    },
    "leisure": {
        "interests": ["nature", "street", "food"],
        "preferred_poi_types": ["公园", "湖滨步道", "街区", "轻松景点"],
        "preferred_keywords": ["休闲漫游", "轻松拍照", "公园", "街区", "夜景", "湖滨"],
        "avoid_keywords": ["赶路", "连续高强度", "偏远折返"],
        "mainstream_preference": 0.4,
        "route_style": "relaxed",
        "query_suffixes": ["休闲景点", "公园", "街区", "夜景", "漫步"],
        "planner_query_hint": "公园 街区 夜景 慢游 轻松",
    },
    "adventure": {
        "interests": ["nature", "niche"],
        "preferred_poi_types": ["风景区", "山岳景区", "森林公园", "徒步步道", "自然保护地"],
        "preferred_keywords": ["徒步", "山野", "自然风景", "森林公园", "户外体验", "古道"],
        "avoid_keywords": ["纯室内", "大型商场", "纯购物", "游客服务中心"],
        "mainstream_preference": 0.28,
        "route_style": "active",
        "query_suffixes": ["徒步", "森林公园", "山岳景区", "户外体验", "古道"],
        "planner_query_hint": "徒步 山野 森林公园 户外 古道",
    },
    "cultural": {
        "interests": ["history_culture", "museum", "street", "indoor"],
        "preferred_poi_types": ["博物馆", "纪念馆", "古迹", "历史文化街区", "美术馆"],
        "preferred_keywords": ["历史文化", "博物馆", "纪念馆", "古建筑", "老街", "人文深度"],
        "avoid_keywords": ["纯购物", "游乐场", "网红打卡", "游客服务中心"],
        "mainstream_preference": 0.32,
        "route_style": "deep",
        "query_suffixes": ["博物馆", "纪念馆", "古迹", "历史文化街区", "人文深度"],
        "planner_query_hint": "博物馆 纪念馆 古迹 历史文化",
    },
}


# ---------- 目的地类型叠加（任意目的地通用，非伊犁专用）----------

KIND_OVERLAY: dict[str, dict[str, Any]] = {
    "city": {
        "search_radius_km": 35.0,
        "search_radius_by_style": {
            "adventure": 95.0,
            "leisure": 45.0,
        },
        "wide_area_search": False,
        "restrict_to_single_city": True,
        "apply_city_museum_filters": True,
        "max_query_count": 14,
        "suffixes_by_style": {
            "adventure": ["森林公园", "郊野公园", "绿道", "江滩"],
        },
    },
    "scenic_region": {
        "search_radius_km": 380.0,
        "wide_area_search": True,
        "restrict_to_single_city": False,
        "apply_city_museum_filters": False,
        "max_query_count": 20,
        "add_interests": ["nature", "city_landmark"],
        "suffixes_by_style": {
            "classic": ["必玩景点", "5A景区", "风景名胜", "草原", "湖泊", "经典环线"],
            "offbeat": ["秘境", "人少景美", "草原", "村落", "徒步"],
            "leisure": ["轻松景点", "草原", "湖泊", "街区", "夜景"],
            "adventure": ["徒步", "古道", "草原", "森林公园", "户外"],
            "cultural": ["民俗", "历史文化街区", "博物馆", "古镇"],
        },
        "keyword_overlay_by_style": {
            "classic": ["必玩景点", "5A景区", "风景名胜", "草原", "湖泊"],
            "offbeat": ["小众景点", "秘境", "本地人爱去"],
            "leisure": ["休闲漫游", "轻松拍照", "草原", "湖泊"],
            "adventure": ["徒步", "山野", "古道", "森林公园"],
            "cultural": ["历史文化", "民俗", "博物馆", "古迹"],
        },
    },
    "province": {
        "search_radius_km": 900.0,
        "wide_area_search": True,
        "restrict_to_single_city": False,
        "apply_city_museum_filters": False,
        "max_query_count": 16,
        "suffixes_by_style": {
            "classic": ["热门景点", "5A景区", "风景名胜", "必去景点"],
            "offbeat": ["小众景点", "老街", "步道"],
            "leisure": ["公园", "休闲景点", "街区"],
            "adventure": ["森林公园", "山岳", "徒步"],
            "cultural": ["博物馆", "古迹", "历史文化"],
        },
    },
}


def normalize_style_key(travel_style: str) -> str:
    text = str(travel_style or "").strip().lower()
    if any(token in text for token in ("小众", "offbeat", "探索")):
        return "offbeat"
    if any(token in text for token in ("休闲", "度假", "leisure")):
        return "leisure"
    if any(token in text for token in ("户外", "探险", "adventure")):
        return "adventure"
    if any(token in text for token in ("文化", "历史", "cultural")):
        return "cultural"
    return "classic"


def build_search_strategy(
    destination: str,
    travel_style: str,
    scope: dict[str, Any] | None = None,
    *,
    likes: list[str] | None = None,
) -> SearchStrategy:
    style_key = normalize_style_key(travel_style)
    if style_key not in STYLE_BASE:
        style_key = "classic"
    kind = infer_destination_kind(destination, scope)
    base = STYLE_BASE[style_key]
    overlay = KIND_OVERLAY.get(kind, KIND_OVERLAY["city"])
    mainstream_preference = float(base["mainstream_preference"])

    interests = list(base["interests"])
    for tag in overlay.get("add_interests", []):
        if tag not in interests:
            interests.append(tag)

    keywords = list(base["preferred_keywords"])
    for item in overlay.get("keyword_overlay_by_style", {}).get(style_key, []):
        if item not in keywords:
            keywords.append(item)

    suffixes = list(base["query_suffixes"])
    for item in overlay.get("suffixes_by_style", {}).get(style_key, []):
        if item not in suffixes:
            suffixes.append(item)

    # 用户偏好词做轻量注入（地标、博物馆、自然等）
    for like in likes or []:
        like_text = str(like).strip()
        if not like_text:
            continue
        if "博物馆" in like_text or "文化" in like_text:
            if "museum" not in interests:
                interests.append("museum")
            if "博物馆" not in keywords:
                keywords.append("博物馆")
        if any(token in like_text for token in ("自然", "风景", "户外")):
            if "nature" not in interests:
                interests.append("nature")
        if any(token in like_text for token in ("地标", "热门", "代表")):
            if "city_landmark" not in interests:
                interests.append("city_landmark")

    seed_names = curated_hotspots_for_style(destination, style_key)
    curated = get_curated_profile(destination)
    radius = float(curated.get("search_radius_km", 0) or 0) if curated else 0.0
    if radius <= 0:
        radius = float(overlay.get("search_radius_km", 35.0))
    style_radius = (overlay.get("search_radius_by_style") or {}).get(style_key)
    if style_radius:
        radius = max(radius, float(style_radius))

    priority_rules = curated_priority_rules(destination, style_key)
    aliases: set[str] = set()
    for part in (destination,):
        aliases |= admin_aliases(part)
    if scope:
        aliases |= set(scope.get("destination_aliases", set()) or set())
        for key in ("province", "city", "resolved_name"):
            aliases |= admin_aliases(scope.get(key, ""))
    if curated and curated.get("parent_province"):
        aliases |= admin_aliases(str(curated["parent_province"]))
    if curated:
        for token in curated.get("adjacent_admin_tokens", ()) or []:
            text = str(token).strip()
            if text:
                aliases.add(text)

    planner_hint = str(base.get("planner_query_hint", "")).strip()
    if not planner_hint and seed_names:
        planner_hint = " ".join(seed_names[:2])

    return SearchStrategy(
        style_key=style_key,
        destination_kind=kind,
        destination=str(destination or "").strip(),
        interests=interests,
        preferred_keywords=keywords[:10],
        preferred_poi_types=list(base["preferred_poi_types"]),
        avoid_keywords=list(base["avoid_keywords"]),
        mainstream_preference=mainstream_preference,
        route_style=str(overlay.get("route_style", base["route_style"])),
        seed_poi_names=seed_names,
        query_suffixes=suffixes,
        planner_query_hint=planner_hint,
        search_radius_km=radius,
        wide_area_search=bool(overlay.get("wide_area_search")),
        restrict_to_single_city=bool(overlay.get("restrict_to_single_city", True)),
        apply_city_museum_filters=bool(overlay.get("apply_city_museum_filters", True)),
        scope_aliases=aliases,
        priority_rules=priority_rules,
        max_query_count=int(overlay.get("max_query_count", 14)),
    )


def merge_strategy_into_persona(persona: dict[str, Any], strategy: SearchStrategy) -> dict[str, Any]:
    """将策略引擎结果写回 persona，供全链路 Agent 与工具消费。"""
    merged = dict(persona or {})
    merged.update(strategy.to_persona_fields())
    merged["style_key"] = strategy.style_key
    merged["interests"] = list(strategy.interests)
    merged["preferred_keywords"] = list(strategy.preferred_keywords)
    merged["preferred_poi_types"] = list(strategy.preferred_poi_types)
    merged["avoid_keywords"] = list(strategy.avoid_keywords)
    merged["mainstream_preference"] = strategy.mainstream_preference
    merged["route_style"] = strategy.route_style
    merged["search_strategy"] = strategy.to_persona_fields()
    return merged


def enrich_scope_with_strategy(scope: dict[str, Any], strategy: SearchStrategy) -> dict[str, Any]:
    enriched = dict(scope or {})
    if strategy.destination_kind in {"scenic_region", "province"}:
        enriched["is_scenic_region"] = strategy.destination_kind == "scenic_region"
        enriched["is_province_level"] = strategy.destination_kind == "province" or bool(enriched.get("is_province_level"))
        if strategy.destination_kind == "scenic_region":
            enriched["is_province_level"] = True
    if strategy.scope_aliases:
        existing = set(enriched.get("destination_aliases", set()) or set())
        enriched["destination_aliases"] = existing | set(strategy.scope_aliases)
    enriched["destination_kind"] = strategy.destination_kind
    return enriched
