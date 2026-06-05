"""意图理解节点产出的出行路由策略，供下游节点只读使用。"""

from __future__ import annotations

from typing import Any

from backend.planning.day_capacity import apply_capacity_to_policy, resolve_day_capacity
from backend.planning.stamina_profile import resolve_stamina_profile


DAY_PACINGS = frozenset({"relaxed", "balanced", "tight"})
ROUTE_PROFILES = frozenset({"driving", "walking", "transit", "mixed"})


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        x = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, x))


def _norm_str(value: Any, allowed: frozenset[str], default: str) -> str:
    s = str(value or "").strip().lower().replace("_", "-")
    if s == "walk":
        s = "walking"
    if s == "drive" or s == "car":
        s = "driving"
    if s in allowed:
        return s
    return default


def default_routing_policy(persona: dict[str, Any], trip_request: dict[str, Any]) -> dict[str, Any]:
    profile = resolve_stamina_profile(persona)
    pacing = profile.day_pacing

    transport = str(persona.get("transport_preference", "") or "")
    if any(k in transport for k in ("步行", "徒步", "walk")):
        route_profile = "walking"
    elif any(k in transport for k in ("地铁", "公交", "轨道", "公共交通")):
        route_profile = "transit"
    elif any(k in transport for k in ("自驾", "驾车", "开车")):
        route_profile = "driving"
    else:
        route_profile = "driving"

    days = max(1, int(trip_request.get("days", 3) or 3))
    capacity = resolve_day_capacity(persona, {"day_pacing": pacing})
    return {
        "max_pois_per_day": capacity.max_pois_cap,
        "daily_activity_load_budget": capacity.daily_load_budget,
        "day_pacing": capacity.day_pacing,
        "route_profile": route_profile,
        "prefer_cluster_by_area": True,
        "prefer_indoor_on_bad_weather": True,
        "strategy_notes": "",
        "source": "defaults",
        "trip_days": days,
    }


def merge_routing_policy(
    llm_payload: dict[str, Any] | None,
    persona: dict[str, Any],
    trip_request: dict[str, Any],
) -> dict[str, Any]:
    """将 LLM JSON 与用户画像/行程默认值合并；不可单独信任原始 LLM 输出。"""
    base = default_routing_policy(persona, trip_request)
    raw = llm_payload if isinstance(llm_payload, dict) else {}

    profile = resolve_stamina_profile(persona)

    pacing = _norm_str(raw.get("day_pacing"), DAY_PACINGS, str(base["day_pacing"]))

    load_budget = _clamp_int(
        raw.get("daily_activity_load_budget"),
        60,
        130,
        int(base["daily_activity_load_budget"]),
    )

    requested_max = raw.get("max_pois_per_day")
    explicit_max: int | None = None
    if requested_max is not None:
        # 意图层给出的上限不能低于体力画像下限，避免出现“一天只排一个点”的失真结果。
        explicit_max = max(
            profile.min_pois_per_day,
            _clamp_int(requested_max, profile.min_pois_per_day, profile.max_pois_per_day, int(base["max_pois_per_day"])),
        )

    capacity = resolve_day_capacity(
        persona,
        {"day_pacing": pacing, "daily_activity_load_budget": load_budget},
        explicit_max_pois=explicit_max,
    )

    route_profile = _norm_str(raw.get("route_profile"), ROUTE_PROFILES, str(base["route_profile"]))

    prefer_cluster = raw.get("prefer_cluster_by_area")
    if prefer_cluster is None:
        prefer_cluster = base["prefer_cluster_by_area"]
    prefer_cluster = bool(prefer_cluster)

    prefer_indoor = raw.get("prefer_indoor_on_bad_weather")
    if prefer_indoor is None:
        prefer_indoor = base["prefer_indoor_on_bad_weather"]
    prefer_indoor = bool(prefer_indoor)

    notes = str(raw.get("strategy_notes") or raw.get("notes") or "").strip()[:500]

    merged = {
        "day_pacing": pacing,
        "route_profile": route_profile,
        "prefer_cluster_by_area": prefer_cluster,
        "prefer_indoor_on_bad_weather": prefer_indoor,
        "strategy_notes": notes,
        "source": "llm_merged" if raw else "defaults_only",
        "trip_days": base["trip_days"],
    }
    return apply_capacity_to_policy(merged, capacity)


INTENT_ROUTING_SYSTEM_PROMPT = """你是旅行规划系统的 Intent Agent（策略子任务）。
你只能基于输入里的 trip_request、persona、weather_rating（若有）输出一个 JSON 对象，不要 markdown，不要解释。

字段与约束：
- daily_activity_load_budget: 整数 60-130，核心字段，表示单日活动负荷上限（100≈一整日有效游览）；轻松档约 82、适中约 100、充沛约 118。
- day_pacing: 只能是 relaxed | balanced | tight（行程松紧）；会微调 daily_activity_load_budget。
- max_pois_per_day: 可选整数；勿填写 1 或 2，系统按体力画像至少排 2–3 个主力点；仅当用户明确说「一天只要一个景点」时才可略降，且不得低于画像下限。
- route_profile: 只能是 driving | walking | transit | mixed；须与 persona.transport_preference 一致或合理（无地铁偏好时不要写 transit）。
- prefer_cluster_by_area: 布尔，是否优先把同一天景点排在相近片区以减少折返。
- prefer_indoor_on_bad_weather: 布尔，天气较差时是否提高室内馆类权重。
- strategy_notes: 字符串，可选，不超过80字，概括当日节奏或禁忌（勿编造具体景点名以外的地点）。

禁止编造输入中不存在的城市、预算或日期。"""
