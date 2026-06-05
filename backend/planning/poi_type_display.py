"""高德地点类型字段到用户可读标签的映射，统一在后端清洗，避免前端拼接原始串。"""

from __future__ import annotations

import re

# 展示优先级：越靠前越适合作为主标签
_TOURISM_TYPE_RANK: dict[str, int] = {
    "博物馆": 1,
    "纪念馆": 2,
    "风景名胜": 3,
    "国家级景点": 4,
    "公园": 5,
    "公园广场": 6,
    "古迹": 7,
    "历史建筑": 8,
    "文化旅游区": 9,
    "步行街": 10,
    "商业街": 11,
    "港口码头": 12,
    "游船": 13,
    "摩天轮": 14,
    "科教文化": 15,
    "科教文化服务": 16,
    "交通设施": 99,
    "交通设施服务": 99,
}

_NOISE_TOKENS = frozenset(
    {
        "交通设施服务",
        "交通设施",
        "科教文化服务",
        "风景名胜",
    }
)

_SPLIT_RE = re.compile(r"[;|；｜]")


def _tokenize(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    parts: list[str] = []
    for chunk in _SPLIT_RE.split(text):
        piece = chunk.strip()
        if not piece:
            continue
        parts.append(piece)
    return parts


def normalize_poi_type_label(raw: str, *, poi_name: str = "") -> str:
    """从高德 type 串提取 1～2 个对用户有意义的标签。"""
    name = str(poi_name or "")
    tokens = _tokenize(raw)

    if _has_any_in(name, ("游船", "邮轮", "渡轮")) or _has_any_in(tokens, ("港口码头", "游船")):
        return "游船体验"

    if _has_any_in(name, ("摩天轮", "之眼")):
        return "城市地标"

    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for token in tokens:
        label = token
        if label in _NOISE_TOKENS and len(tokens) > 1:
            continue
        if "博物馆" in label:
            label = "博物馆"
        elif "风景名胜" in label and "国家级" in " ".join(tokens):
            label = "国家级景点"
        elif "公园广场" in label or label == "公园":
            label = "城市公园"
        elif "港口码头" in label:
            label = "码头"
        elif "科教文化" in label:
            label = "文化场馆"
        if label in seen:
            continue
        seen.add(label)
        rank = _TOURISM_TYPE_RANK.get(label, _TOURISM_TYPE_RANK.get(token, 50))
        ranked.append((rank, label))

    if not ranked:
        return "景点"

    ranked.sort(key=lambda item: item[0])
    top = [label for _, label in ranked[:2]]
    return " · ".join(top)


def _has_any_in(text: str | list[str], needles: tuple[str, ...]) -> bool:
    if isinstance(text, list):
        blob = " ".join(text)
    else:
        blob = str(text)
    return any(n in blob for n in needles)
