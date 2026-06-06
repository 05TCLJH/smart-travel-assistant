"""面向外部展示的数据清洗器。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


PUBLIC_PERSONA_FIELDS = ("name", "travel_style", "stamina", "budget_style")


def public_persona_profile(persona: dict[str, Any] | None) -> dict[str, Any]:
    source = persona if isinstance(persona, dict) else {}
    return {field: source[field] for field in PUBLIC_PERSONA_FIELDS if field in source}


def sanitize_trip_result(trip_result: dict[str, Any] | None) -> dict[str, Any]:
    payload = deepcopy(trip_result if isinstance(trip_result, dict) else {})
    payload["persona"] = public_persona_profile(payload.get("persona"))
    return payload
