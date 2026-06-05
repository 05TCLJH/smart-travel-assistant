"""单日行程容量：由体力画像统一派生负荷预算与景点数上下限。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.planning.activity_load import LOAD_LIGHT
from backend.planning.stamina_profile import (
    apply_pacing_adjustment,
    resolve_stamina_profile,
    user_poi_cap_override,
)

DAY_PACINGS = frozenset({"relaxed", "balanced", "tight"})


@dataclass(frozen=True)
class DayCapacity:
    daily_load_budget: int
    max_pois_cap: int
    min_pois_per_day: int
    day_pacing: str = "balanced"
    stamina_key: str = "适中"


def derive_max_pois_cap(daily_load_budget: int, profile_min: int = 2, profile_max: int = 6) -> int:
    """负荷推导的乐观槽位数，再与体力画像的 min/max 夹紧。"""
    budget = max(60, min(int(daily_load_budget or 100), 130))
    load_based = max(1, min(6, budget // LOAD_LIGHT))
    return max(profile_min, min(profile_max, load_based))


def resolve_day_capacity(
    persona: dict[str, Any] | None = None,
    routing_policy: dict[str, Any] | None = None,
    *,
    explicit_max_pois: int | None = None,
) -> DayCapacity:
    """合并 persona / routing_policy，输出一致的负荷预算与景点数上下限。"""
    persona = persona or {}
    rp = dict(routing_policy or {})
    profile = resolve_stamina_profile(persona)

    pacing = str(rp.get("day_pacing") or "").strip().lower()
    if pacing not in DAY_PACINGS:
        pacing = profile.day_pacing
    rp["day_pacing"] = pacing

    if rp.get("daily_activity_load_budget") is not None:
        try:
            load = max(60, min(int(rp["daily_activity_load_budget"]), 130))
        except (TypeError, ValueError):
            load = apply_pacing_adjustment(profile.daily_load_budget, pacing)
    elif persona.get("daily_activity_load_budget") is not None:
        try:
            load = max(60, min(int(persona["daily_activity_load_budget"]), 130))
        except (TypeError, ValueError):
            load = apply_pacing_adjustment(profile.daily_load_budget, pacing)
    else:
        load = apply_pacing_adjustment(profile.daily_load_budget, pacing)

    cap = derive_max_pois_cap(load, profile.min_pois_per_day, profile.max_pois_per_day)
    min_pois = profile.min_pois_per_day

    override = explicit_max_pois
    if override is None:
        override = user_poi_cap_override(persona)
    if override is not None:
        cap = max(min_pois, min(int(override), cap))

    return DayCapacity(
        daily_load_budget=load,
        max_pois_cap=cap,
        min_pois_per_day=min_pois,
        day_pacing=pacing,
        stamina_key=profile.key,
    )


def apply_capacity_to_policy(policy: dict[str, Any], capacity: DayCapacity) -> dict[str, Any]:
    merged = dict(policy)
    merged["daily_activity_load_budget"] = capacity.daily_load_budget
    merged["max_pois_per_day"] = capacity.max_pois_cap
    merged["min_pois_per_day"] = capacity.min_pois_per_day
    merged["day_pacing"] = capacity.day_pacing
    merged["stamina_key"] = capacity.stamina_key
    return merged
