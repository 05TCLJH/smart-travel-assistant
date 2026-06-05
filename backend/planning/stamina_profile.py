"""体力画像：三档统一配置，供检索、装箱、时间轴与意图策略共用。

对外只暴露三档标准值：轻松、适中、充沛。
历史五档滑条、弱中强与一到五数字等输入都在此归一化，避免多套表各自为政。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CANONICAL_STAMINA = ("轻松", "适中", "充沛")
DEFAULT_STAMINA = "适中"


@dataclass(frozen=True)
class StaminaProfile:
    """单日行程容量的唯一来源。"""

    key: str
    daily_load_budget: int
    min_pois_per_day: int
    max_pois_per_day: int
    day_pacing: str
    min_day_load_ratio: float
    """装箱后若整日负荷占比低于该值，触发同日补点。"""

    @property
    def label(self) -> str:
        return self.key


_PROFILES: dict[str, StaminaProfile] = {
    "轻松": StaminaProfile(
        key="轻松",
        daily_load_budget=82,
        min_pois_per_day=2,
        max_pois_per_day=4,
        day_pacing="relaxed",
        min_day_load_ratio=0.42,
    ),
    "适中": StaminaProfile(
        key="适中",
        daily_load_budget=100,
        min_pois_per_day=3,
        max_pois_per_day=5,
        day_pacing="balanced",
        min_day_load_ratio=0.55,
    ),
    "充沛": StaminaProfile(
        key="充沛",
        daily_load_budget=118,
        min_pois_per_day=3,
        max_pois_per_day=6,
        day_pacing="tight",
        min_day_load_ratio=0.50,
    ),
}

# 历史别名与五档滑条文案统一映射到标准档位
_STAMINA_ALIASES: dict[str, str] = {
    "弱": "轻松",
    "低": "轻松",
    "较弱": "轻松",
    "很累": "轻松",
    "轻松游": "轻松",
    "较轻松": "轻松",
    "中等": "适中",
    "中": "适中",
    "平衡": "适中",
    "一般": "适中",
    "强": "充沛",
    "高": "充沛",
    "较强": "充沛",
    "较充沛": "充沛",
    "体力好": "充沛",
    "充沛": "充沛",
}

_ENERGY_LEVEL_TO_STAMINA = {1: "轻松", 2: "适中", 3: "充沛"}


def normalize_stamina(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return DEFAULT_STAMINA
    if text in _PROFILES:
        return text
    mapped = _STAMINA_ALIASES.get(text)
    if mapped:
        return mapped
    try:
        level = int(float(text))
        if level in _ENERGY_LEVEL_TO_STAMINA:
            return _ENERGY_LEVEL_TO_STAMINA[level]
        if level <= 1:
            return "轻松"
        if level >= 3:
            return "充沛"
        return "适中"
    except (TypeError, ValueError):
        pass
    lowered = text.lower()
    if lowered in {"relaxed", "low", "weak"}:
        return "轻松"
    if lowered in {"balanced", "medium", "normal"}:
        return "适中"
    if lowered in {"tight", "high", "strong"}:
        return "充沛"
    return DEFAULT_STAMINA


def resolve_stamina_profile(persona: dict[str, Any] | None = None, raw_stamina: Any = None) -> StaminaProfile:
    persona = persona or {}
    key = normalize_stamina(raw_stamina if raw_stamina is not None else persona.get("stamina"))
    return _PROFILES[key]


def stamina_energy_level(stamina: Any) -> int:
    key = normalize_stamina(stamina)
    return {"轻松": 1, "适中": 2, "充沛": 3}[key]


def apply_pacing_adjustment(base_budget: int, day_pacing: str) -> int:
    pacing = str(day_pacing or "balanced").strip().lower()
    budget = int(base_budget)
    if pacing == "relaxed":
        budget = int(budget * 0.92)
    elif pacing == "tight":
        budget = int(budget * 1.06)
    return max(60, min(budget, 130))


def user_poi_cap_override(persona: dict[str, Any] | None) -> int | None:
    """仅当用户显式写入 poi_cap_override / max_pois_per_day 时压低上限。"""
    persona = persona or {}
    if persona.get("poi_cap_override") is True:
        try:
            return max(1, min(6, int(persona.get("max_pois_per_day") or 0)))
        except (TypeError, ValueError):
            return None
    return None
