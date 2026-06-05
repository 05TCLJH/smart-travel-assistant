"""可选目的地知识库与通用目的地类型推断。

知识库条目用于提升检索质量，不是系统运行前提。
无条目时，由检索策略模块根据「风格 × 目的地类型」自动生成检索策略。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.core.paths import PROJECT_ROOT
from backend.knowledge.guide_visit_estimate import guide_profile_for_knowledge
from backend.knowledge.visit_profiles import hotspot_entry_name, normalize_visit_profile
from backend.tools.grounding_tools import admin_aliases, is_province_level_destination_name, normalize_admin_name


KNOWLEDGE_PATH = PROJECT_ROOT / "data" / "destination_knowledge.json"
CURATED_VISIT_PATH = PROJECT_ROOT / "data" / "curated_visit_profiles.json"
DESTINATION_KINDS = ("city", "scenic_region", "province")

SCENIC_NAME_HINTS = (
    "自治州",
    "地区",
    "盟",
    "环线",
    "草原",
    "风景区",
    "国家公园",
    "大峡谷",
    "湖泊",
)


@lru_cache(maxsize=1)
def _load_catalog() -> dict[str, dict[str, Any]]:
    if not KNOWLEDGE_PATH.exists():
        return {}
    try:
        raw = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _normalize_key(text: str) -> str:
    normalized = str(text or "").strip().replace(" ", "")
    for suffix in (
        "维吾尔自治区",
        "壮族自治区",
        "回族自治区",
        "特别行政区",
        "自治区",
        "自治州",
        "地区",
        "省",
        "市",
        "州",
    ):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized.strip()


def resolve_destination_key(destination: str) -> str | None:
    text = str(destination or "").strip()
    if not text:
        return None
    normalized = _normalize_key(text)
    catalog = _load_catalog()
    for key, profile in catalog.items():
        if normalized == _normalize_key(key):
            return key
        for alias in profile.get("aliases", ()):
            if normalized == _normalize_key(str(alias)):
                return key
    return None


def get_curated_profile(destination: str) -> dict[str, Any] | None:
    key = resolve_destination_key(destination)
    if not key:
        return None
    profile = _load_catalog().get(key)
    return dict(profile) if isinstance(profile, dict) else None


def catalog_scope_aliases(destination: str) -> set[str]:
    """知识库目的地对应的行政区别名（用于范围匹配与冲突判断）。"""
    profile = get_curated_profile(destination)
    if not profile:
        return set()
    aliases: set[str] = set()
    for alias in profile.get("aliases", ()):
        aliases |= {token for token in admin_aliases(str(alias)) if token}
    parent = str(profile.get("parent_province", "")).strip()
    if parent:
        aliases |= {token for token in admin_aliases(parent) if token}
        if not parent.endswith("省"):
            aliases.add(parent + "省")
    anchor = str(profile.get("geocode_anchor", "")).strip()
    if anchor:
        aliases |= {token for token in admin_aliases(anchor) if token}
    for token in profile.get("adjacent_admin_tokens", ()) or []:
        text = str(token).strip()
        if text:
            aliases.add(text)
            aliases |= {t for t in admin_aliases(text) if t}
    return aliases


def resolve_geocode_query(destination: str) -> str:
    """风景环线等模糊目的地：用知识库锚点地理编码，避免「川西」落到无关城市。"""
    text = str(destination or "").strip()
    profile = get_curated_profile(text)
    if not profile:
        return text
    anchor = str(profile.get("geocode_anchor", "")).strip()
    if anchor:
        return anchor
    parent = str(profile.get("parent_province", "")).strip()
    if profile.get("region_type") in {"scenic_region", "province"} and parent:
        return parent if parent.endswith("省") else f"{parent}省"
    return text


def infer_destination_kind(destination: str, scope: dict[str, Any] | None = None) -> str:
    """推断目的地类型：city | scenic_region | province（无需知识库条目）。"""
    profile = get_curated_profile(destination)
    if profile and profile.get("region_type") in {"city", "scenic_region", "province"}:
        return str(profile["region_type"])

    scope = scope or {}
    if scope.get("destination_kind") in DESTINATION_KINDS:
        return str(scope["destination_kind"])

    city = str(scope.get("city", "")).strip()
    if city and not is_province_level_destination_name(destination):
        if any(hint in city for hint in SCENIC_NAME_HINTS):
            return "scenic_region"
        return "city"

    if scope.get("is_province_level") and not city:
        return "province"

    resolved = " ".join(
        str(scope.get(key, "")).strip()
        for key in ("destination", "resolved_name", "city", "province", "district")
    )
    haystack = f"{destination} {resolved}"
    if any(hint in haystack for hint in SCENIC_NAME_HINTS):
        return "scenic_region"

    if is_province_level_destination_name(destination):
        return "province"

    return "city"


def iter_all_hotspot_names(profile: dict[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    hotspots = profile.get("hotspots") or {}
    if not isinstance(hotspots, dict):
        return names
    for bucket in hotspots.values():
        if not isinstance(bucket, list):
            continue
        for entry in bucket:
            text = hotspot_entry_name(entry)
            if text and text not in seen:
                seen.add(text)
                names.append(text)
    return names


@lru_cache(maxsize=1)
def _load_curated_visit_seeds() -> dict[str, dict[str, Any]]:
    if not CURATED_VISIT_PATH.exists():
        return {}
    try:
        raw = json.loads(CURATED_VISIT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(key).strip(): dict(value)
        for key, value in raw.items()
        if not str(key).startswith("_") and isinstance(value, dict)
    }


def visit_profiles_for_destination(destination: str) -> dict[str, dict[str, Any]]:
    """由知识库 hotspots + 导游规则动态生成；JSON 中不再存储 visit_profiles。"""
    profile = get_curated_profile(destination)
    if not profile:
        return {}
    region_type = str(profile.get("region_type", "city") or "city")
    curated = _load_curated_visit_seeds()
    out: dict[str, dict[str, Any]] = {}
    for seed in iter_all_hotspot_names(profile):
        if seed in curated:
            raw = curated[seed]
        else:
            raw = guide_profile_for_knowledge(seed, region_type=region_type)
        out[seed] = normalize_visit_profile(raw, poi_name=seed)

    # 全国名景校准表并入匹配池，提高「故宫」「赛里木湖」等子串命中率
    for key, raw in curated.items():
        if key not in out:
            out[key] = normalize_visit_profile(raw, poi_name=key)
    return out


def merged_visit_profiles_for_destination(destination: str) -> dict[str, dict[str, Any]]:
    return visit_profiles_for_destination(destination)


def curated_hotspots_for_style(destination: str, style_key: str) -> list[str]:
    profile = get_curated_profile(destination)
    if not profile:
        return []
    hotspots: dict[str, list] = profile.get("hotspots", {})
    style = str(style_key or "classic").strip().lower()
    bucket_map = {
        "classic": ("classic", "city_landmark", "nature"),
        "offbeat": ("offbeat", "nature"),
        "leisure": ("leisure", "nature", "classic"),
        "adventure": ("adventure", "nature"),
        "cultural": ("cultural", "city_landmark", "classic"),
    }
    buckets = bucket_map.get(style, ("classic", "nature"))
    names: list[str] = []
    seen: set[str] = set()
    for bucket in buckets:
        for name in hotspots.get(bucket, []):
            text = hotspot_entry_name(name)
            if text and text not in seen:
                seen.add(text)
                names.append(text)
    return names


def curated_priority_rules(destination: str, style_key: str) -> dict[str, list[str]]:
    profile = get_curated_profile(destination)
    if not profile:
        return {}
    hotspots: dict[str, list[str]] = profile.get("hotspots", {})
    style = str(style_key or "classic").strip().lower()
    if style == "classic":
        return {
            "city_landmark": list(hotspots.get("classic", [])),
            "nature": list(hotspots.get("nature", hotspots.get("classic", []))),
            "history_culture": list(hotspots.get("city_landmark", [])),
        }
    if style == "offbeat":
        return {
            "niche": list(hotspots.get("offbeat", [])),
            "nature": list(hotspots.get("nature", [])),
        }
    if style == "adventure":
        adventure = list(hotspots.get("adventure", []))
        return {
            "niche": adventure or list(hotspots.get("offbeat", [])),
            "nature": list(hotspots.get("nature", [])) or adventure,
        }
    if style == "leisure":
        return {"nature": list(hotspots.get("leisure", [])), "street": list(hotspots.get("classic", []))}
    if style == "cultural":
        return {
            "history_culture": list(hotspots.get("cultural", hotspots.get("city_landmark", []))),
            "museum": list(hotspots.get("cultural", [])),
        }
    return {}


# 兼容旧引用
def get_destination_profile(destination: str) -> dict[str, Any] | None:
    return get_curated_profile(destination)


def hotspot_names_for_style(destination: str, style_key: str) -> list[str]:
    return curated_hotspots_for_style(destination, style_key)


def catalog_priority_rules(destination: str, style_key: str) -> dict[str, list[str]]:
    return curated_priority_rules(destination, style_key)


def is_scenic_region(destination: str) -> bool:
    return infer_destination_kind(destination, None) == "scenic_region"


def scenic_search_radius_km(destination: str) -> float | None:
    profile = get_curated_profile(destination)
    if not profile or profile.get("region_type") != "scenic_region":
        return None
    try:
        return float(profile.get("search_radius_km", 0) or 0)
    except (TypeError, ValueError):
        return None
