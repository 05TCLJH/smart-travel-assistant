"""游览点：行程与地图上的最小游览单元。

高德常把同一母景区拆成多个子地点，如子广场、观景台、入口、记忆馆等。本模块在
「名称景区簇」之外，用地址母景区加近距离关联做并查集归并，输出单一锚点地点，
避免候选列表与地图重复打点。

下游统一使用 visit_site_id / cluster_key_for_poi（二者一致）。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from backend.planning.poi_retrieval import geo as poi_geo
from backend.planning.poi_roles import (
    PoiRole,
    eligible_for_scenic_cluster,
    is_itinerary_eligible_role,
    resolve_poi_role,
)

# 同一母景区内子地点的最大间距（公里）；仅在与地址或名称信号一致时启用
PROXIMITY_MERGE_KM = 0.28

_SCENIC_SUFFIXES = (
    "空中草原",
    "河谷草原",
    "国家森林公园",
    "国家级风景名胜区",
    "自治区级风景名胜区",
    "风景名胜区",
    "风景旅游区",
    "旅游度假区",
    "旅游风景区",
    "森林公园",
    "大草原",
    "草原",
    "东广场",
    "西广场",
    "南广场",
    "北广场",
    "风景区",
    "景区",
    "景点",
    "露营地",
    "度假村",
    "营地",
    "滑翔伞基地",
    "游客中心",
    "停车场",
    "出口",
    "入口",
    "服务区",
)

_ADDRESS_VENUE_SUFFIXES = (
    "民俗风貌区",
    "风貌区",
    "风景名胜区",
    "国家级风景名胜区",
    "风景旅游区",
    "旅游度假区",
    "森林公园",
    "国家公园",
    "古城",
    "古镇",
    "古街",
    "历史文化街区",
    "步行街",
    "风情街",
    "老街",
    "景区",
    "风景区",
    "主题公园",
    "度假区",
    "大峡谷",
    "大草原",
)

_GENERIC_PREFIXES = ("G30", "连霍高速", "高速")
_PAREN_CLUSTER = re.compile(r"[（(]([^)）]+)[)）]")
_ADDRESS_VENUE_RE = re.compile(
    r"([\u4e00-\u9fff]{2,28}(?:"
    + "|".join(re.escape(s) for s in _ADDRESS_VENUE_SUFFIXES)
    + r"))"
)
_INNER_LANDMARK_MARKERS = ("步行街", "古街", "古镇", "古城", "历史文化街区", "民俗风貌", "风情区", "老街", "风貌区")

_KNOWN_PARENT_SCENIC_CHILDREN: dict[str, tuple[str, ...]] = {
    "西湖": (
        "雷峰塔",
        "九溪烟树",
        "九溪",
        "苏堤",
        "白堤",
        "断桥",
        "三潭印月",
        "花港观鱼",
        "曲院风荷",
        "柳浪闻莺",
        "南屏晚钟",
        "平湖秋月",
        "双峰插云",
        "阮墩环碧",
        "吴山天风",
        "玉皇飞云",
        "满陇桂雨",
        "虎跑",
        "龙井问茶",
    ),
}


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _suffix_stem(raw: str) -> str:
    key = str(raw or "").strip()
    if not key:
        return ""
    for suffix in _SCENIC_SUFFIXES:
        if suffix in key:
            key = key.split(suffix, 1)[0]
    for token in _GENERIC_PREFIXES:
        if token in key:
            key = key.split(token, 1)[0]
    return key.strip("·-—－()（）")


def _stem_to_cluster_id(stem: str, fallback_text: str) -> str:
    if not stem:
        return ""
    if len(stem) >= 4:
        return stem[:4]
    return stem or fallback_text[:6]


def _known_parent_scenic_key(text: str) -> str:
    blob = str(text or "").strip()
    if not blob:
        return ""
    for parent, children in _KNOWN_PARENT_SCENIC_CHILDREN.items():
        if parent in blob:
            return parent
        if any(child in blob for child in children):
            return parent
    return ""


def _inner_matches_landmark(inner: str, seeds: set[str]) -> bool:
    if any(marker in inner for marker in _INNER_LANDMARK_MARKERS):
        return True
    for seed in seeds:
        if not seed:
            continue
        if seed in inner or inner in seed:
            return True
    return False


def _cluster_from_parenthetical(name: str, role: PoiRole, seeds: set[str]) -> str | None:
    if role not in {PoiRole.STREET_LANDMARK, PoiRole.SCENIC, PoiRole.CULTURAL, PoiRole.CITY_LANDMARK, PoiRole.UNKNOWN}:
        return None
    text = str(name or "").strip()
    m = _PAREN_CLUSTER.search(text)
    if not m:
        return None
    inner = m.group(1).strip().rstrip("店").strip().rstrip("分店").strip()
    if len(inner) < 2 or not _inner_matches_landmark(inner, seeds):
        return None
    if inner.isdigit() or inner in {"总店", "旗舰店"}:
        return None
    if re.search(r"(?:^|\s)G\d+", inner) or any(k in inner for k in ("高速", "高架", "省道", "国道", "立交")):
        return None
    stem = _suffix_stem(inner)
    label = stem or inner
    if len(label) < 2:
        return None
    return _stem_to_cluster_id(label, inner)


def address_venue_key(poi: dict[str, Any], seed_names: Iterable[str] | None = None) -> str:
    """从地址/名称中提取母景区键（如洪崖洞民俗风貌区 → 洪崖洞）。"""
    seeds = {str(s).strip() for s in (seed_names or []) if str(s).strip()}
    blob = f"{poi.get('name', '')} {poi.get('address', '')}".strip()
    if not blob:
        return ""
    known_parent = _known_parent_scenic_key(blob)
    if known_parent:
        return known_parent

    for seed in sorted(seeds, key=len, reverse=True):
        if len(seed) >= 3 and seed in blob:
            return _stem_to_cluster_id(_suffix_stem(seed), seed)

    best = ""
    for match in _ADDRESS_VENUE_RE.finditer(blob):
        venue = match.group(1).strip()
        if len(venue) < 4:
            continue
        stem = _suffix_stem(venue)
        key = _stem_to_cluster_id(stem or venue, venue)
        if len(key) > len(best):
            best = key
    return best


def seed_names_from_persona(persona: dict[str, Any] | None) -> set[str]:
    seeds: set[str] = set()
    for name in (persona or {}).get("destination_hotspots", ()) or []:
        text = str(name).strip()
        if text:
            seeds.add(text)
    for name in (persona or {}).get("search_strategy", {}).get("seed_poi_names", ()) or []:
        text = str(name).strip()
        if text:
            seeds.add(text)
    return seeds


def scenic_cluster_key(
    name: str,
    seed_names: Iterable[str] | None = None,
    *,
    poi: dict[str, Any] | None = None,
) -> str:
    """名称维度的景区簇主键；非簇归并角色返回空串。"""
    text = str(name or "").strip()
    if not text:
        return ""

    role = resolve_poi_role(poi) if poi else PoiRole.UNKNOWN
    if poi is None:
        from backend.planning.poi_roles import classify_poi_role

        role = classify_poi_role(text)
    if not eligible_for_scenic_cluster(role):
        return ""

    seeds = {str(s).strip() for s in (seed_names or []) if str(s).strip()}
    known_parent = _known_parent_scenic_key(text)
    if known_parent:
        return known_parent
    paren_cluster = _cluster_from_parenthetical(text, role, seeds)
    if paren_cluster:
        return paren_cluster

    stem = _suffix_stem(text)
    for seed in sorted(seeds, key=len, reverse=True):
        if seed in text:
            return _stem_to_cluster_id(_suffix_stem(seed), seed)

    for seed in sorted(seeds, key=len, reverse=True):
        prefix_len = min(4, len(seed)) if len(seed) >= 3 else len(seed)
        prefix = seed[:prefix_len]
        if prefix and text.startswith(prefix):
            return _stem_to_cluster_id(stem, text)

    return _stem_to_cluster_id(stem, text)


def visit_site_id(poi: dict[str, Any], seed_names: Iterable[str] | None = None) -> str:
    """单 POI 的游览点标识：优先地址母景区，其次名称簇，否则用名称本身。"""
    seeds = set(seed_names or [])
    role = resolve_poi_role(poi)
    if not eligible_for_scenic_cluster(role):
        return str(poi.get("name", "")).strip()

    addr_key = address_venue_key(poi, seeds)
    name_key = scenic_cluster_key(str(poi.get("name", "")), seeds, poi=poi)
    if addr_key:
        return addr_key
    return name_key or str(poi.get("name", "")).strip()


def cluster_key_for_poi(poi: dict[str, Any], seed_names: Iterable[str] | None = None) -> str:
    cached = str(poi.get("visit_site_id", "")).strip()
    if cached:
        return cached
    return visit_site_id(poi, seed_names)


def _poi_sort_score(poi: dict[str, Any]) -> tuple[float, float, int, int, int]:
    name = str(poi.get("name", ""))
    anchor_bonus = 0
    if any(k in name for k in ("风貌区", "风景区", "风景名胜区", "古镇", "古城", "国家森林公园")):
        anchor_bonus += 40
    if any(k in name for k in ("广场", "售票", "出口", "入口", "驿站", "记忆", "炮台")):
        anchor_bonus -= 15
    return (
        float(poi.get("popularity_score", 0.0) or poi.get("suitability_score", 0.0) or 0.0) + anchor_bonus,
        float(poi.get("constraint_score", 0.0) or 0.0),
        1 if poi.get("knowledge_seed") else 0,
        -len(name),
        1 if poi.get("visit_site_label") else 0,
    )


def _merge_signals(poi: dict[str, Any], seeds: set[str]) -> list[str]:
    signals: list[str] = []
    name_key = scenic_cluster_key(str(poi.get("name", "")), seeds, poi=poi)
    if name_key:
        signals.append(f"name:{name_key}")
    addr_key = address_venue_key(poi, seeds)
    if addr_key:
        signals.append(f"addr:{addr_key}")
    return signals


def _proximity_should_merge(a: dict[str, Any], b: dict[str, Any], seeds: set[str]) -> bool:
    av_a, av_b = address_venue_key(a, seeds), address_venue_key(b, seeds)
    if av_a and av_b and av_a == av_b:
        return True

    blob_a = f"{a.get('name', '')} {a.get('address', '')}"
    blob_b = f"{b.get('name', '')} {b.get('address', '')}"
    nk_a = scenic_cluster_key(str(a.get("name", "")), seeds, poi=a)
    nk_b = scenic_cluster_key(str(b.get("name", "")), seeds, poi=b)
    if nk_a and len(nk_a) >= 2 and (nk_a in blob_b or nk_a in str(b.get("name", ""))):
        return True
    if nk_b and len(nk_b) >= 2 and (nk_b in blob_a or nk_b in str(a.get("name", ""))):
        return True

    for seed in sorted(seeds, key=len, reverse=True):
        if len(seed) >= 4 and seed in blob_a and seed in blob_b:
            return True
    return False


def _group_site_id(members: list[dict[str, Any]], seeds: set[str]) -> str:
    keys = [visit_site_id(p, seeds) for p in members]
    keys = [k for k in keys if k]
    if not keys:
        return ""
    return max(set(keys), key=len)


def _pick_anchor(members: list[dict[str, Any]], seeds: set[str]) -> dict[str, Any]:
    ranked = sorted(members, key=_poi_sort_score, reverse=True)
    anchor = dict(ranked[0])
    others = [str(p.get("name", "")).strip() for p in ranked[1:] if str(p.get("name", "")).strip()]
    site_id = _group_site_id(members, seeds) or visit_site_id(anchor, seeds)
    anchor["visit_site_id"] = site_id
    anchor["visit_site_label"] = str(anchor.get("name", "")).strip()
    if others:
        anchor["visit_site_members"] = others
        anchor["visit_site_note"] = f"含同区关联点：{'、'.join(others[:4])}" + ("等" if len(others) > 4 else "")
    return anchor


def merge_to_visit_sites(
    pois: list[dict[str, Any]],
    *,
    seed_names: Iterable[str] | None = None,
    max_per_site: int = 1,
) -> list[dict[str, Any]]:
    """将可簇归并的 POI 归并为游览点锚点；其余行程点原样保留。"""
    if max_per_site < 1:
        max_per_site = 1
    seeds = set(seed_names or [])

    cluster_pool: list[dict[str, Any]] = []
    passthrough: list[dict[str, Any]] = []
    for poi in pois:
        role = resolve_poi_role(poi)
        if not is_itinerary_eligible_role(role):
            continue
        if eligible_for_scenic_cluster(role):
            cluster_pool.append(poi)
        else:
            passthrough.append(poi)

    if not cluster_pool:
        return sorted(passthrough, key=_poi_sort_score, reverse=True)

    coords = [poi_geo.parse_lnglat(str(p.get("location", ""))) for p in cluster_pool]
    uf = _UnionFind(len(cluster_pool))
    signal_owner: dict[str, int] = {}

    for index, poi in enumerate(cluster_pool):
        for signal in _merge_signals(poi, seeds):
            if signal in signal_owner:
                uf.union(index, signal_owner[signal])
            else:
                signal_owner[signal] = index

    for i in range(len(cluster_pool)):
        for j in range(i + 1, len(cluster_pool)):
            if uf.find(i) == uf.find(j):
                continue
            if not coords[i] or not coords[j]:
                continue
            if poi_geo.distance_km(coords[i], coords[j]) > PROXIMITY_MERGE_KM:
                continue
            if _proximity_should_merge(cluster_pool[i], cluster_pool[j], seeds):
                uf.union(i, j)

    groups: dict[int, list[dict[str, Any]]] = {}
    for index, poi in enumerate(cluster_pool):
        root = uf.find(index)
        groups.setdefault(root, []).append(poi)

    kept: list[dict[str, Any]] = []
    for members in groups.values():
        kept.append(_pick_anchor(members, seeds))

    merged = [*kept, *passthrough]
    return sorted(merged, key=_poi_sort_score, reverse=True)


def dedupe_by_scenic_cluster(
    pois: list[dict[str, Any]],
    *,
    seed_names: Iterable[str] | None = None,
    max_per_cluster: int = 1,
) -> list[dict[str, Any]]:
    """兼容旧名：内部已改为游览点归并。"""
    return merge_to_visit_sites(pois, seed_names=seed_names, max_per_site=max_per_cluster)
