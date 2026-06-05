"""统一规划画像：按 1-7 天、体力、范围与风格连续推导检索和排期参数。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from backend.planning.day_capacity import DayCapacity, resolve_day_capacity
from backend.tools.grounding_tools import strict_style_mode

MIN_SUPPORTED_DAYS = 1
MAX_SUPPORTED_DAYS = 7


@dataclass(frozen=True)
class PlanningProfile:
    """统一规划入口，避免按具体天数分别写策略。"""

    days: int
    duration_ratio: float
    capacity: DayCapacity
    strict_style: bool
    is_wide_area: bool
    target_slots: int
    candidate_floor: int
    candidate_guardrail: int
    planning_pool_target: int
    candidate_expansion_threshold: int
    query_budget: int
    enrichment_limit: int
    supplement_affinity_floor: float


def _clamp_int(value: float, lower: int, upper: int) -> int:
    return max(lower, min(int(math.ceil(value)), upper))


def _duration_ratio(days: int) -> float:
    clamped_days = max(MIN_SUPPORTED_DAYS, min(int(days), MAX_SUPPORTED_DAYS))
    if MAX_SUPPORTED_DAYS == MIN_SUPPORTED_DAYS:
        return 0.0
    return (clamped_days - MIN_SUPPORTED_DAYS) / (MAX_SUPPORTED_DAYS - MIN_SUPPORTED_DAYS)


def resolve_planning_profile(
    persona: dict[str, Any] | None,
    *,
    days: int | None = None,
    max_per_day: int | None = None,
    is_wide_area: bool = False,
    seed_count: int = 0,
    routing_policy: dict[str, Any] | None = None,
) -> PlanningProfile:
    """统一推导 1-7 天行程的供给、筛选与补点参数。"""

    persona = persona or {}
    resolved_days = max(MIN_SUPPORTED_DAYS, int(days or persona.get("trip_days", 3) or 3))
    ratio = _duration_ratio(resolved_days)
    capacity = resolve_day_capacity(persona, routing_policy)
    per_day_cap = max(1, int(max_per_day or capacity.max_pois_cap or 1))
    target_slots = resolved_days * per_day_cap
    strict_mode = strict_style_mode(persona)

    reserve_slots = math.ceil(per_day_cap * (0.8 + ratio * 1.1)) + math.ceil(
        resolved_days * (0.35 + ratio * 0.25 + (0.15 if is_wide_area else 0.0))
    )
    candidate_floor = max(
        6,
        math.ceil(target_slots * (0.56 + ratio * 0.16)),
        math.ceil(resolved_days * (2.2 + ratio * 0.8)),
    )
    candidate_guardrail = max(
        8,
        min(
            target_slots + reserve_slots,
            math.ceil(target_slots * (1.08 + ratio * 0.18) + resolved_days * 0.8),
        ),
    )
    planning_pool_target = max(
        candidate_guardrail,
        math.ceil(target_slots * (1.16 + ratio * 0.14) + resolved_days * 0.6),
    )
    candidate_expansion_threshold = max(
        candidate_floor,
        math.ceil(planning_pool_target * (0.72 + ratio * 0.06)),
    )

    query_budget = _clamp_int(
        7 + resolved_days * 1.4 + ratio * 1.6 + (2.0 if is_wide_area else 0.0),
        8,
        24 if is_wide_area else 20,
    )
    enrichment_floor = 28 if is_wide_area else 18
    enrichment_ceiling = 60 if is_wide_area else 42
    coverage_floor = seed_count + math.ceil(8 + resolved_days * (1.0 + (0.35 if is_wide_area else 0.2)))
    enrichment_limit = _clamp_int(
        max(
            enrichment_floor,
            planning_pool_target + resolved_days * (0.7 + ratio * 0.4) + (3.5 if is_wide_area else 0.0),
            coverage_floor,
        ),
        enrichment_floor,
        enrichment_ceiling,
    )

    supplement_affinity_floor = min(
        46.0,
        (40.0 if strict_mode else 32.0) + ratio * 3.0 + (1.0 if is_wide_area else 0.0),
    )

    return PlanningProfile(
        days=resolved_days,
        duration_ratio=round(ratio, 3),
        capacity=capacity,
        strict_style=strict_mode,
        is_wide_area=is_wide_area,
        target_slots=target_slots,
        candidate_floor=candidate_floor,
        candidate_guardrail=candidate_guardrail,
        planning_pool_target=planning_pool_target,
        candidate_expansion_threshold=candidate_expansion_threshold,
        query_budget=query_budget,
        enrichment_limit=enrichment_limit,
        supplement_affinity_floor=round(supplement_affinity_floor, 2),
    )
