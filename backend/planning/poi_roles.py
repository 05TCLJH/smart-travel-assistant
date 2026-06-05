"""景点候选项行程角色：检索、归一化、景区簇去重与规划共用的语义层。

原则：
- 高德分类字段决定「是什么」（零售、餐饮、风景、文化等）
- 景区簇仅对可参与行程主线的风景、街区与文化点做归并
- 零售、餐饮、附属设施在归一化入口即剔除，不靠品牌黑名单
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

BLOCKED_POI_NAME_KEYWORDS = (
    "停车场",
    "售票处",
    "检票处",
    "游客中心",
    "公交站",
    "地铁站",
    "派出所",
    "服务区",
    "售票点",
    "验票点",
    "检票口",
    "精品客栈",
    "客栈",
    "纪念品",
    "办公楼",
    "体育场",
    "建设中",
    "不对外开放",
    "文创商店",
    "旗舰店",
    "礼品店",
)


class PoiRole(str, Enum):
    SCENIC = "scenic"
    CULTURAL = "cultural"
    STREET_LANDMARK = "street_landmark"
    CITY_LANDMARK = "city_landmark"
    RETAIL = "retail"
    FOOD = "food"
    LODGING = "lodging"
    TRANSPORT = "transport"
    AUXILIARY = "auxiliary"
    UNKNOWN = "unknown"


# 参与行程候选池的角色
ITINERARY_ELIGIBLE_ROLES = frozenset(
    {
        PoiRole.SCENIC,
        PoiRole.CULTURAL,
        PoiRole.STREET_LANDMARK,
        PoiRole.CITY_LANDMARK,
        PoiRole.UNKNOWN,
    }
)

# 可做景区簇归并（同一品牌景区/历史街区只留一个代表点）
SCENIC_CLUSTER_ROLES = frozenset(
    {
        PoiRole.SCENIC,
        PoiRole.CULTURAL,
        PoiRole.STREET_LANDMARK,
        PoiRole.CITY_LANDMARK,
        PoiRole.UNKNOWN,  # 无分类字段的风景点名仍参与簇归并（如「喀拉峻大草原」）
    }
)

_TYPECODE_PREFIX_ROLE: tuple[tuple[str, PoiRole], ...] = (
    ("050", PoiRole.FOOD),
    ("060", PoiRole.RETAIL),
    ("070", PoiRole.AUXILIARY),
    ("080", PoiRole.SCENIC),  # 体育休闲 / 游乐园等，下面名称再细分
    ("100", PoiRole.TRANSPORT),
    ("110", PoiRole.SCENIC),
    ("120", PoiRole.TRANSPORT),
    ("130", PoiRole.LODGING),
    ("140", PoiRole.CULTURAL),
    ("150", PoiRole.TRANSPORT),
    ("160", PoiRole.TRANSPORT),
    ("170", PoiRole.AUXILIARY),
    ("190", PoiRole.AUXILIARY),
)

_TYPE_TEXT_ROLE: tuple[tuple[str, PoiRole], ...] = (
    ("购物服务", PoiRole.RETAIL),
    ("购物", PoiRole.RETAIL),
    ("餐饮服务", PoiRole.FOOD),
    ("住宿服务", PoiRole.LODGING),
    ("风景名胜", PoiRole.SCENIC),
    ("公园广场", PoiRole.SCENIC),
    ("博物馆", PoiRole.CULTURAL),
    ("科教文化", PoiRole.CULTURAL),
    ("文化传媒", PoiRole.CULTURAL),
    ("交通设施", PoiRole.TRANSPORT),
    ("汽车服务", PoiRole.AUXILIARY),
    ("生活服务", PoiRole.AUXILIARY),
    ("商务住宅", PoiRole.AUXILIARY),
    ("政府机构", PoiRole.AUXILIARY),
    ("公司企业", PoiRole.AUXILIARY),
    ("医疗保健", PoiRole.AUXILIARY),
)

_NAME_ROLE_HINTS: tuple[tuple[str, PoiRole], ...] = (
    ("博物馆", PoiRole.CULTURAL),
    ("纪念馆", PoiRole.CULTURAL),
    ("博物院", PoiRole.CULTURAL),
    ("古镇", PoiRole.STREET_LANDMARK),
    ("古街", PoiRole.STREET_LANDMARK),
    ("步行街", PoiRole.STREET_LANDMARK),
    ("历史文化街区", PoiRole.STREET_LANDMARK),
    ("民俗风貌", PoiRole.STREET_LANDMARK),
    ("风景区", PoiRole.SCENIC),
    ("风景名胜区", PoiRole.SCENIC),
    ("国家森林公园", PoiRole.SCENIC),
    ("森林公园", PoiRole.SCENIC),
    ("草原", PoiRole.SCENIC),
    ("大峡谷", PoiRole.SCENIC),
    ("湖泊", PoiRole.SCENIC),
    ("湿地", PoiRole.SCENIC),
    ("雪山", PoiRole.SCENIC),
    ("索道", PoiRole.SCENIC),
    ("广场", PoiRole.CITY_LANDMARK),
    ("观景台", PoiRole.SCENIC),
)


def _extract_typecodes(type_text: str) -> list[str]:
    raw = str(type_text or "")
    return re.findall(r"\d{6}", raw)


def _role_from_typecode(type_text: str) -> PoiRole | None:
    for code in _extract_typecodes(type_text):
        prefix = code[:3]
        for rule_prefix, role in _TYPECODE_PREFIX_ROLE:
            if prefix == rule_prefix or code.startswith(rule_prefix):
                return role
    return None


def _role_from_type_text(type_text: str) -> PoiRole | None:
    text = str(type_text or "")
    for marker, role in _TYPE_TEXT_ROLE:
        if marker in text:
            return role
    return None


def _role_from_name(name: str) -> PoiRole | None:
    text = str(name or "").strip()
    if not text:
        return None
    if any(token in text for token in BLOCKED_POI_NAME_KEYWORDS):
        return PoiRole.AUXILIARY
    for marker, role in _NAME_ROLE_HINTS:
        if marker in text:
            return role
    return None


def classify_poi_role(name: str, type_text: str = "") -> PoiRole:
    """统一角色判定：typecode > 类型文本 > 名称启发。"""
    role = _role_from_typecode(type_text)
    if role is None:
        role = _role_from_type_text(type_text)
    if role is None:
        role = _role_from_name(name)
    if role is None:
        return PoiRole.UNKNOWN
    # 游乐园等仍归景区类；纯零售类型不被名称里的「广场」覆盖
    if role == PoiRole.SCENIC:
        return role
    name_role = _role_from_name(name)
    if name_role and role in {PoiRole.RETAIL, PoiRole.FOOD, PoiRole.AUXILIARY, PoiRole.LODGING}:
        return role
    if name_role and role == PoiRole.UNKNOWN:
        return name_role
    if name_role and role == PoiRole.CITY_LANDMARK and name_role in SCENIC_CLUSTER_ROLES:
        return name_role
    return role


def is_itinerary_eligible_role(role: PoiRole | str | None) -> bool:
    if isinstance(role, PoiRole):
        return role in ITINERARY_ELIGIBLE_ROLES
    try:
        return PoiRole(str(role or "")) in ITINERARY_ELIGIBLE_ROLES
    except ValueError:
        return False


def eligible_for_scenic_cluster(role: PoiRole | str | None) -> bool:
    if isinstance(role, PoiRole):
        return role in SCENIC_CLUSTER_ROLES
    try:
        return PoiRole(str(role or "")) in SCENIC_CLUSTER_ROLES
    except ValueError:
        return False


def resolve_poi_role(poi: dict[str, Any]) -> PoiRole:
    cached = poi.get("poi_role")
    if cached:
        try:
            return PoiRole(str(cached))
        except ValueError:
            pass
    type_text = str(poi.get("type", poi.get("typecode", "")) or "")
    return classify_poi_role(str(poi.get("name", "")), type_text)


def attach_poi_role(poi: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(poi)
    role = classify_poi_role(str(enriched.get("name", "")), str(enriched.get("type", enriched.get("typecode", "")) or ""))
    enriched["poi_role"] = role.value
    return enriched
