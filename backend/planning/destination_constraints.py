"""目的地地理约束：检索半径、跨区景点与守卫审阅共用同一套规则。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.knowledge.destination_catalog import (
    catalog_scope_aliases,
    curated_hotspots_for_style,
    get_curated_profile,
    infer_destination_kind,
    scenic_search_radius_km,
)
from backend.planning.search_strategy import STYLE_KEYS, build_search_strategy
from backend.tools.grounding_tools import admin_aliases, normalize_admin_name


def _admin_haystack(poi: dict[str, Any]) -> str:
    parts = [
        str(poi.get("province", "")).strip(),
        str(poi.get("city", "")).strip(),
        str(poi.get("district", "")).strip(),
        str(poi.get("address", "")).strip(),
    ]
    normalized = " ".join(
        item
        for item in {
            " ".join(p for p in parts if p),
            *(normalize_admin_name(p) for p in parts if p),
        }
        if item
    )
    return normalized


def _hotspot_names(destination: str, persona: dict[str, Any] | None) -> frozenset[str]:
    profile = get_curated_profile(destination)
    if not profile:
        return frozenset()
    style_key = str((persona or {}).get("style_key", "classic")).strip()
    if style_key not in STYLE_KEYS:
        style_key = "classic"
    names = curated_hotspots_for_style(profile, style_key)
    seeds: set[str] = set()
    for name in names:
        text = str(name).strip()
        if text:
            seeds.add(text)
    return frozenset(seeds)


@dataclass(frozen=True)
class DestinationConstraintProfile:
    """由知识库 + SearchStrategy 派生；guard / grounding 不得各自维护一套规则。"""

    destination: str
    region_type: str
    parent_province: str
    search_radius_km: float
    scope_aliases: frozenset[str]
    seed_names: frozenset[str]
    adjacent_admin_tokens: frozenset[str]

    @classmethod
    def resolve(
        cls,
        destination: str,
        persona: dict[str, Any] | None = None,
        scope: dict[str, Any] | None = None,
    ) -> DestinationConstraintProfile:
        dest = str(destination or "").strip()
        profile = get_curated_profile(dest)
        region_type = infer_destination_kind(dest, profile)
        scope = scope or {}
        parent = str((profile or {}).get("parent_province", "")).strip() or str(scope.get("province", "")).strip()
        radius = float(scenic_search_radius_km(dest) or 0)
        if radius <= 0:
            scope_stub = {
                "city": str(scope.get("city", "")).strip() or str((persona or {}).get("destination_city", "")).strip(),
                "province": parent,
                "is_province_level": bool(scope.get("is_province_level")),
                "resolved_name": str(scope.get("resolved_name", "")).strip(),
            }
            strategy = build_search_strategy(
                dest,
                str((persona or {}).get("travel_style", "经典热门")),
                scope_stub,
                likes=(persona or {}).get("likes"),
            )
            radius = float(strategy.search_radius_km)
            region_type = strategy.destination_kind

        aliases = set(catalog_scope_aliases(dest) | {token for token in admin_aliases(dest) if token})
        alias_keys = ("province", "city", "resolved_name") if region_type in {"province", "scenic_region"} else ("city", "resolved_name")
        for key in alias_keys:
            aliases |= {token for token in admin_aliases(scope.get(key, "")) if token}
        adjacent = frozenset(
            str(token).strip()
            for token in (profile or {}).get("adjacent_admin_tokens", ())
            if str(token).strip()
        )
        seeds = _hotspot_names(dest, persona)
        if persona:
            for name in persona.get("destination_hotspots", ()) or []:
                text = str(name).strip()
                if text:
                    seeds = seeds | frozenset({text})
        return cls(
            destination=dest,
            region_type=region_type,
            parent_province=parent,
            search_radius_km=radius,
            scope_aliases=frozenset(aliases),
            seed_names=seeds,
            adjacent_admin_tokens=adjacent,
        )

    @property
    def is_wide_area(self) -> bool:
        return self.region_type in {"scenic_region", "province"}

    @property
    def remote_distance_threshold_km(self) -> float:
        if self.is_wide_area:
            return max(120.0, self.search_radius_km * 0.88)
        return 18.0

    def matches_seed_name(self, poi_name: str) -> bool:
        name = str(poi_name or "").strip()
        if not name or not self.seed_names:
            return False
        return any(seed in name or name in seed for seed in self.seed_names)

    def poi_in_scope(self, poi: dict[str, Any]) -> bool:
        if bool(poi.get("knowledge_seed")):
            return True
        if self.matches_seed_name(str(poi.get("name", ""))):
            return True

        haystack = _admin_haystack(poi)
        if not haystack:
            # 高德召回常缺省市区字段：城市目的地默认视为在范围内，由距离分档处理偏远点
            if not self.is_wide_area:
                return True
            dist = float(poi.get("distance_to_destination_km", 0.0) or 0.0)
            return self.search_radius_km > 0 and dist <= self.search_radius_km

        if self.scope_aliases and any(token in haystack for token in self.scope_aliases):
            return True

        if self.adjacent_admin_tokens and any(token in haystack for token in self.adjacent_admin_tokens):
            return True

        if self.parent_province and self.is_wide_area:
            parent_tokens = admin_aliases(self.parent_province)
            if not self.parent_province.endswith("省"):
                parent_tokens.add(self.parent_province + "省")
            if any(token and token in haystack for token in parent_tokens):
                return True

        if self.region_type == "province" and not str(poi.get("province", "")).strip():
            dist = float(poi.get("distance_to_destination_km", 0.0) or 0.0)
            if self.search_radius_km > 0 and dist <= self.search_radius_km:
                return True

        if self.is_wide_area:
            dist = float(poi.get("distance_to_destination_km", 0.0) or 0.0)
            if self.search_radius_km > 0 and dist <= self.search_radius_km and self.matches_seed_name(str(poi.get("name", ""))):
                return True

        if not self.is_wide_area:
            dest_tokens = admin_aliases(self.destination)
            return any(token and token in haystack for token in dest_tokens)
        return False

    def admin_conflict(self, poi: dict[str, Any]) -> bool:
        return not self.poi_in_scope(poi)


def resolve_constraint_profile(
    destination: str,
    persona: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> DestinationConstraintProfile:
    return DestinationConstraintProfile.resolve(destination, persona, scope)
