"""旅行风格判断工具，集中管理画像风格与内部风格键之间的映射逻辑。"""

from __future__ import annotations

from typing import Any

from backend.planning.search_strategy import normalize_style_key


def resolve_persona_style_key(persona: dict[str, Any] | None) -> str:
    """从画像中解析统一风格键。"""
    data = persona or {}
    style_key = str(data.get("style_key", "")).strip().lower()
    if style_key in {"classic", "offbeat", "leisure", "adventure", "cultural"}:
        return style_key
    return normalize_style_key(str(data.get("travel_style", "")))


def is_classic_style(persona: dict[str, Any] | None) -> bool:
    return resolve_persona_style_key(persona) == "classic"


def is_offbeat_style(persona: dict[str, Any] | None) -> bool:
    return resolve_persona_style_key(persona) == "offbeat"


def is_leisure_style(persona: dict[str, Any] | None) -> bool:
    return resolve_persona_style_key(persona) == "leisure"


def is_adventure_style(persona: dict[str, Any] | None) -> bool:
    return resolve_persona_style_key(persona) == "adventure"


def is_cultural_style(persona: dict[str, Any] | None) -> bool:
    return resolve_persona_style_key(persona) == "cultural"
