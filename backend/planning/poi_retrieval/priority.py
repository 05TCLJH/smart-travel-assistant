"""景点优先级评分，只依赖策略中的优先规则，不做城市硬编码。"""

from __future__ import annotations

from typing import Any

from backend.planning.poi_retrieval.policy import PoiRetrievalPolicy
from backend.tools.grounding_tools import normalize_poi_tags


def destination_priority_score(policy: PoiRetrievalPolicy, poi: dict[str, Any]) -> float:
    rules = policy.priority_rules
    if not rules:
        return 0.0
    tags = normalize_poi_tags(poi)
    name = str(poi.get("name", "")).strip()
    score = 0.0
    for tag, keywords in rules.items():
        if tag in tags:
            for keyword in keywords:
                if keyword and keyword in name:
                    score += 18.0
    if "history_culture" in tags and any(token in name for token in rules.get("history_culture", [])):
        score += 8.0
    if "museum" in tags and any(token in name for token in ("专题", "书画", "昆虫", "藏品", "老酒", "巧克力")):
        score -= 10.0
    return score


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def raw_row_priority(
    policy: PoiRetrievalPolicy,
    row: dict[str, Any],
    *,
    destination_priority_fn,
) -> tuple[float, int, int]:
    name = str(row.get("name", "")).strip()
    query = str(row.get("_query", "")).strip()
    query_index = _safe_int(row.get("_query_index", 99), 99)
    query_order = _safe_int(row.get("_query_order", 99), 99)
    score = 0.0
    for hotspot in policy.seed_poi_names:
        if hotspot and hotspot in name:
            score += 28.0
    if query and query in name:
        score += 18.0
    if name == query:
        score += 22.0
    if name in policy.exact_query_names:
        score += 30.0
    if query in policy.exact_query_names and any(separator in name for separator in ("-", "－", "—")) and query in name:
        score -= 22.0
    if any(token in query for token in ("小众", "本地人爱去", "老街", "步道", "创意园", "市集")):
        if any(token in name for token in ("老街", "街区", "步道", "创意园", "市集", "码头", "公园", "巷")):
            score += 16.0
        if any(token in name for token in ("广场", "游客中心", "服务中心", "地标", "国旗")):
            score -= 18.0
    score += destination_priority_fn({"name": name, "type": str(row.get("typecode", ""))})
    if any(token in name for token in ("博物馆", "纪念馆", "故居", "广场", "长城", "公园", "宫", "寺")):
        score += 4.0
    if any(
        token in name
        for token in ("办公楼", "检票处", "文创", "旗舰店", "体育场", "球场", "售票处", "服务中心", "观众服务中心")
    ):
        score -= 40.0
    return (-score, query_index, query_order)
