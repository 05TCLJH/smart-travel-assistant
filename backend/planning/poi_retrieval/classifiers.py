"""景点名称与类型分类规则，供检索前与归一化阶段共用。"""

from __future__ import annotations

from typing import Any

from backend.planning.poi_roles import BLOCKED_POI_NAME_KEYWORDS

MUSEUM_NAME_TOKENS = ("博物馆", "纪念馆", "陈列馆")
LOW_VALUE_SHOPPING_NAME_TOKENS = (
    "专卖店",
    "专营店",
    "旗舰店",
    "分店",
    "门店",
    "体验店",
    "购物中心",
    "商场",
    "奥特莱斯",
)
LOW_VALUE_SHOPPING_TYPE_TOKENS = (
    "购物服务",
    "专卖店",
    "专营店",
    "商铺",
    "商场",
)


def guess_tags(name: str, type_text: str = "") -> list[str]:
    haystack = f"{name} {type_text}"
    tags: list[str] = []
    if any(token in haystack for token in ("博物馆", "纪念")):
        tags.append("历史文化")
    if any(token in haystack for token in ("古镇", "古城", "街区", "寺", "祠", "书院")):
        tags.append("历史文化")
    if any(token in haystack for token in ("阁", "楼", "塔", "城")):
        tags.append("城市地标")
    if any(token in haystack for token in ("公园", "山", "湖", "湿地", "森林")):
        tags.append("自然风景")
    if any(token in haystack for token in ("步行街", "商业街", "巷", "坊")):
        tags.append("街区")
    return tags


def is_low_value_shopping_branch(name: str, type_text: str = "") -> bool:
    """识别不适合作为行程候选的零售分店与购物点。"""

    text_name = str(name or "").strip()
    text_type = str(type_text or "").strip()
    haystack = f"{text_name} {text_type}"
    if not text_name:
        return False
    if not any(token in haystack for token in LOW_VALUE_SHOPPING_TYPE_TOKENS):
        return False
    if any(token in text_name for token in ("景区", "古镇", "古城", "街区", "步行街")):
        return False
    if any(token in haystack for token in LOW_VALUE_SHOPPING_NAME_TOKENS):
        return True
    return "购物服务" in text_type and len(text_name) <= 6


def is_usable_raw_poi(row: dict[str, Any]) -> bool:
    from backend.planning.poi_roles import classify_poi_role, is_itinerary_eligible_role

    name = str(row.get("name", "")).strip()
    type_text = str(row.get("type", row.get("typecode", ""))).strip()
    if not name:
        return False
    if any(token in name for token in BLOCKED_POI_NAME_KEYWORDS):
        return False
    if is_low_value_shopping_branch(name, type_text):
        return False
    if type_text.startswith("150") or type_text.startswith("0703"):
        return False
    role = classify_poi_role(name, type_text)
    return is_itinerary_eligible_role(role)


def is_complex_sub_poi(name: str, type_text: str) -> bool:
    if any(separator in name for separator in ("-", "（", "·")) and any(
        token in name
        for token in ("纪念馆", "博物馆", "景区", "故居", "遗址", "阁", "寺", "广场", "公园", "长城")
    ):
        return True
    if any(separator in name for separator in ("-", "（", "·")) and any(
        token in name
        for token in (
            "角楼",
            "城楼",
            "国旗",
            "入口",
            "出口",
            "东门",
            "西门",
            "南门",
            "北门",
            "午门",
            "神武门",
            "东华门",
            "西华门",
            "观景台",
            "展厅",
            "陈列馆",
            "文华殿",
            "武英殿",
            "殿",
            "楼",
            "坊",
            "厅",
        )
    ):
        return True
    if "风景名胜相关" in type_text and any(
        token in name for token in ("陵墓", "谯平山", "朱克靳", "段德昌", "栈道", "纪念亭")
    ):
        return True
    return False


def is_food_poi_type(type_text: str) -> bool:
    return type_text.startswith("05") or "餐饮服务" in type_text


def dedupe_name_key(name: str) -> str:
    text = str(name or "").strip()
    for separator in ("-", "（", "·"):
        if separator in text:
            return text.split(separator, 1)[0].strip()
    return text


def name_signature(name: str) -> str:
    text = str(name or "").strip()
    for token in ("中国", "南京市", "北京市", "上海市", "西安市", "江苏省", "陕西省", "江西省"):
        text = text.replace(token, "")
    for token in ("博物馆", "纪念馆", "历史文化街区", "景区", "公园", "广场"):
        text = text.replace(token, "")
    return text.strip()


def has_similar_poi_name(rows: list[dict[str, Any]], name: str) -> bool:
    target = name_signature(name)
    if not target:
        return False
    for row in rows:
        existing = name_signature(str(row.get("name", "")).strip())
        if not existing:
            continue
        if target == existing or target in existing or existing in target:
            return True
    return False
