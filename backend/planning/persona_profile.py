"""人物画像风格预设。
集中维护各旅行风格对应的偏好词与行程诉求，避免前端和后端各自维护一份近似配置。
"""

from __future__ import annotations

from typing import Any

from backend.planning.search_strategy import normalize_style_key


STYLE_PERSONA_PRESETS: dict[str, dict[str, list[str]]] = {
    "classic": {
        "likes": ["地标", "城市代表性景点"],
        "must_have": ["不绕路", "节奏清晰"],
    },
    "offbeat": {
        "likes": ["小众景点", "本地体验"],
        "must_have": ["避开人流", "路线灵活"],
    },
    "leisure": {
        "likes": ["舒适休闲", "拍照打卡"],
        "must_have": ["节奏宽松", "休息充足"],
    },
    "adventure": {
        "likes": ["自然风景", "户外活动"],
        "must_have": ["体验丰富", "机动空间"],
    },
    "cultural": {
        "likes": ["博物馆", "历史文化"],
        "must_have": ["内容扎实", "讲解友好"],
    },
}


def apply_style_persona_preset(persona: dict[str, Any]) -> dict[str, Any]:
    """按旅行风格补齐默认偏好，显式传入的同名字段优先保留。"""
    merged = dict(persona or {})
    preset = STYLE_PERSONA_PRESETS.get(normalize_style_key(merged.get("travel_style")), STYLE_PERSONA_PRESETS["classic"])
    for field in ("likes", "must_have"):
        current = merged.get(field)
        if isinstance(current, list) and any(str(item).strip() for item in current):
            merged[field] = [str(item).strip() for item in current if str(item).strip()]
            continue
        merged[field] = list(preset[field])
    current_dislikes = merged.get("dislikes")
    if isinstance(current_dislikes, list):
        merged["dislikes"] = [str(item).strip() for item in current_dislikes if str(item).strip()]
    else:
        merged["dislikes"] = []
    return merged
