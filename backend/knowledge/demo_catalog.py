"""离线演示景点目录，与目的地知识库分离维护。

- 目的地知识库文件负责提供检索种子，供线上高德检索使用
- 演示景点文件负责提供完整景点记录，供无高德、失败回退与候选补全使用
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from backend.core.paths import PROJECT_ROOT
from backend.knowledge.destination_catalog import _normalize_key, resolve_destination_key
from backend.planning.poi_retrieval.classifiers import guess_tags
from backend.planning.poi_retrieval.geo import distance_km, parse_lnglat

DEMO_POIS_PATH = PROJECT_ROOT / "data" / "demo_pois.json"


@lru_cache(maxsize=1)
def _load_demo_library() -> dict[str, dict[str, Any]]:
    if not DEMO_POIS_PATH.exists():
        return {}
    try:
        raw = json.loads(DEMO_POIS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def resolve_demo_destination_key(destination: str) -> str | None:
    """将用户输入映射到 demo_pois.json 中的键（优先走知识库别名）。"""
    text = str(destination or "").strip()
    if not text:
        return None
    catalog_key = resolve_destination_key(text)
    library = _load_demo_library()
    if catalog_key and catalog_key in library:
        return catalog_key
    normalized = _normalize_key(text)
    for key, entry in library.items():
        if normalized == _normalize_key(key):
            return key
        for alias in entry.get("aliases", ()):
            if normalized == _normalize_key(str(alias)):
                return key
    return None


def list_demo_destinations() -> list[str]:
    return sorted(_load_demo_library().keys())


def has_demo_coverage(destination: str) -> bool:
    return resolve_demo_destination_key(destination) is not None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def matches_query_hint(poi: dict[str, Any], query_hint: str) -> bool:
    hint = str(query_hint or "").strip()
    if not hint:
        return True
    haystack = " ".join(
        [
            str(poi.get("name", "")),
            str(poi.get("type", "")),
            " ".join(map(str, poi.get("knowledge_tags", []))),
        ]
    )
    return any(token and token in haystack for token in hint.split())


def normalize_demo_poi(raw: dict[str, Any], *, geo: dict[str, float], resolved_name: str, admin1: str) -> dict[str, Any]:
    poi = dict(raw)
    name = str(poi.get("name", "")).strip()
    type_text = str(poi.get("type", "")).strip()
    anchor = (float(geo["lng"]), float(geo["lat"]))
    pair = parse_lnglat(str(poi.get("location", "")))
    dist = round(distance_km(anchor, pair), 1) if pair else 0.0
    poi.setdefault("knowledge_tags", guess_tags(name, type_text))
    poi.update(
        {
            "provider": "demo-local-dataset",
            "ticket": "未知",
            "cost": "",
            "knowledge_hit": True,
            "city": resolved_name,
            "province": admin1,
            "distance_to_destination_km": dist,
            "popularity_score": round(_safe_float(poi.get("rating"), 4.6) * 18 + max(0, 20 - dist), 2),
            "source": "demo_poi_library",
        }
    )
    return poi


def get_demo_destination_meta(destination: str) -> dict[str, Any] | None:
    key = resolve_demo_destination_key(destination)
    if not key:
        return None
    entry = _load_demo_library().get(key)
    if not isinstance(entry, dict):
        return None
    geo = entry.get("geo") or {}
    return {
        "destination": destination,
        "demo_key": key,
        "resolved_name": str(entry.get("resolved_name", key)),
        "geo": {"lng": float(geo.get("lng", 0)), "lat": float(geo.get("lat", 0))},
        "country": "中国",
        "admin1": str(entry.get("admin1", "")),
    }


def load_demo_pois(destination: str, query_hint: str = "") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """返回 (地点元数据, 规范化 POI 列表)。无演示覆盖时 POI 为空。"""
    text = str(destination or "").strip()
    meta = get_demo_destination_meta(text)
    if meta is None:
        return (
            {
                "destination": text,
                "resolved_name": text,
                "geo": {"lng": 0.0, "lat": 0.0},
                "country": "中国",
                "admin1": "",
            },
            [],
        )
    key = meta["demo_key"]
    entry = _load_demo_library()[key]
    geo = meta["geo"]
    pois = [
        normalize_demo_poi(item, geo=geo, resolved_name=meta["resolved_name"], admin1=meta["admin1"])
        for item in entry.get("pois", [])
        if isinstance(item, dict)
    ]
    filtered = [p for p in pois if matches_query_hint(p, query_hint)]
    return meta, filtered or pois
