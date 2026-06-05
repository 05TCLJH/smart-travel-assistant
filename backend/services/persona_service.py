"""用户画像的公开视图与规划视图分离。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.core.public_views import PUBLIC_PERSONA_FIELDS, public_persona_profile
from backend.planning.budget_style import normalize_budget_style
from backend.planning.day_capacity import resolve_day_capacity
from backend.planning.persona_profile import apply_style_persona_preset
from backend.planning.search_strategy import build_search_strategy, merge_strategy_into_persona, normalize_style_key
from backend.planning.stamina_profile import normalize_stamina, resolve_stamina_profile

DEFAULT_PUBLIC_PERSONA = {
    "name": "旅行者",
    "travel_style": "经典热门",
    "stamina": "适中",
    "budget_style": "舒适",
}

DEFAULT_INTERNAL_PERSONA = {
    "transport_preference": "打车/网约车优先",
    "likes": [],
    "dislikes": [],
    "must_have": [],
}


class PersonaService:
    """公开接口只返回前端已采集字段，规划时再补齐内部推理字段。"""

    def load(self) -> dict[str, Any]:
        return public_persona_profile(DEFAULT_PUBLIC_PERSONA)

    def save(self, update: dict[str, Any]) -> dict[str, Any]:
        merged = self._normalize_public({**DEFAULT_PUBLIC_PERSONA, **self._pick_public_fields(update)})
        return public_persona_profile(merged)

    def reset(self) -> dict[str, Any]:
        return self.load()

    def enrich(self, incoming: dict[str, Any] | None, trip_request: dict[str, Any] | None = None) -> dict[str, Any]:
        public_profile = self._normalize_public({**DEFAULT_PUBLIC_PERSONA, **self._pick_public_fields(incoming)})
        request = trip_request or {}
        destination = str(request.get("destination", "")).strip()
        days = max(1, int(request.get("days", 3) or 3))
        budget = float(request.get("budget", 3000) or 3000)

        internal = dict(public_profile)
        internal.update(DEFAULT_INTERNAL_PERSONA)
        internal = apply_style_persona_preset(internal)
        internal["transport_preference"] = self._infer_transport_preference(internal, budget)

        strategy = build_search_strategy(
            destination,
            str(internal.get("travel_style", DEFAULT_PUBLIC_PERSONA["travel_style"])),
            scope=None,
            likes=list(internal.get("likes", [])),
        )
        internal = merge_strategy_into_persona(internal, strategy)

        internal["trip_days"] = days
        internal["trip_budget"] = budget
        internal["budget_per_day"] = round(budget / days, 2)
        internal["budget_per_person_day"] = round(budget / days, 2)
        internal["budget_tier"] = "宽裕" if internal["budget_per_day"] >= 900 else "适中" if internal["budget_per_day"] >= 500 else "紧凑"
        internal["current_destination"] = destination

        capacity = resolve_day_capacity(internal)
        profile = resolve_stamina_profile(internal)
        internal["stamina"] = profile.key
        internal["stamina_profile"] = profile.key
        internal["daily_activity_load_budget"] = capacity.daily_load_budget
        internal["max_pois_per_day"] = capacity.max_pois_cap
        internal["min_pois_per_day"] = capacity.min_pois_per_day

        internal["persona_summary"] = self._summary(internal)
        internal["preference_summary"] = (
            f"用户画像：{internal['persona_summary']}；"
            f"本次 {days} 天预算 {int(budget)} 元；"
            f"节奏按 {internal.get('stamina', '适中')} 体力组织。"
        )
        internal["planning_constraints"] = (
            f"当前为 1 人出行，计划 {days} 天，"
            f"日均预算约 {int(internal['budget_per_day'])} 元；"
            f"体力节奏 {internal.get('stamina', '适中')}（单日负荷上限约 {internal.get('daily_activity_load_budget', 100)}，"
            f"每日至少 {internal.get('min_pois_per_day', 3)} 个主力点、最多约 {internal.get('max_pois_per_day', 5)} 个）；"
            f"风格模式 {internal.get('style_key', 'classic')}；"
            f"目的地类型 {internal.get('destination_region_type', 'city')}。"
        )
        hotspots = internal.get("destination_hotspots") or []
        if hotspots:
            internal["planning_constraints"] += f" 可参考热点种子：{'、'.join(hotspots[:8])}。"

        return internal

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """Compatibility helper for older internal tests and callers."""
        return self.enrich(data, {"destination": "", "days": 3, "budget": 3000})

    @staticmethod
    def _summary(persona: dict[str, Any]) -> str:
        style = str(persona.get("travel_style", DEFAULT_PUBLIC_PERSONA["travel_style"])).strip() or DEFAULT_PUBLIC_PERSONA["travel_style"]
        kind = str(persona.get("destination_region_type", "city"))
        stamina = str(persona.get("stamina", DEFAULT_PUBLIC_PERSONA["stamina"])).strip() or DEFAULT_PUBLIC_PERSONA["stamina"]
        return f"{style}风格（{kind}），{stamina}体力节奏"

    @staticmethod
    def _pick_public_fields(data: dict[str, Any] | None) -> dict[str, Any]:
        source = data or {}
        return {field: source[field] for field in PUBLIC_PERSONA_FIELDS if field in source}

    @staticmethod
    def _normalize_public(data: dict[str, Any]) -> dict[str, Any]:
        normalized = deepcopy(DEFAULT_PUBLIC_PERSONA)
        normalized.update(PersonaService._pick_public_fields(data))

        name = str(normalized.get("name", "")).strip()
        travel_style = str(normalized.get("travel_style", "")).strip()
        stamina = normalize_stamina(normalized.get("stamina"))
        budget_style = normalize_budget_style(normalized.get("budget_style"))

        normalized["name"] = name or DEFAULT_PUBLIC_PERSONA["name"]
        normalized["travel_style"] = travel_style or DEFAULT_PUBLIC_PERSONA["travel_style"]
        normalized["stamina"] = stamina
        normalized["budget_style"] = budget_style
        return normalized

    @staticmethod
    def _infer_transport_preference(persona: dict[str, Any], budget: float) -> str:
        budget_style = str(persona.get("budget_style", "")).strip()
        stamina = str(persona.get("stamina", "")).strip()
        if budget_style in {"缁忔祹", "economy"} or budget < 1200:
            return "地铁/公交优先"
        if stamina == "杞绘澗":
            return "地铁/公交优先"
        return "打车/网约车优先"


# 兼容外部引用
def _style_key(style: str) -> str:
    return normalize_style_key(style)
