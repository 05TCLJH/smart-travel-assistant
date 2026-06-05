"""规划工具兼容出口。

将候选评分、候选筛选、行程组装等能力统一转发到 backend.planning 下的专职模块，
保留历史导入路径，避免现有调用链和测试用例中断。
"""

from __future__ import annotations

from backend.planning.candidate_scoring import (
    MAINSTREAM_NEGATIVE_KEYWORDS,
    MAINSTREAM_POSITIVE_KEYWORDS,
    OFFBEAT_NEGATIVE_KEYWORDS,
    OFFBEAT_POSITIVE_KEYWORDS,
    mainstream_score,
    passes_style_guard,
    rank_candidates,
    score_candidate,
)
from backend.planning.candidate_selection import (
    candidate_family,
    cluster_candidates_by_district,
    distribute_candidates,
    flatten_route_points,
    select_diverse_candidates,
)
from backend.planning.itinerary_builder import build_plan, build_timeline, summarize_theme

__all__ = [
    "MAINSTREAM_NEGATIVE_KEYWORDS",
    "MAINSTREAM_POSITIVE_KEYWORDS",
    "OFFBEAT_NEGATIVE_KEYWORDS",
    "OFFBEAT_POSITIVE_KEYWORDS",
    "build_plan",
    "build_timeline",
    "candidate_family",
    "cluster_candidates_by_district",
    "distribute_candidates",
    "flatten_route_points",
    "mainstream_score",
    "passes_style_guard",
    "rank_candidates",
    "score_candidate",
    "select_diverse_candidates",
    "summarize_theme",
]
