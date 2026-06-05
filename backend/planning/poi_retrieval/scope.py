"""目的地范围匹配（大区检索 / 行政区别名）。"""

from __future__ import annotations

from typing import Any

from backend.tools.grounding_tools import normalize_admin_name


def build_scope_haystack(*parts: Any) -> str:
    return " ".join(
        item
        for item in {
            *(str(part or "").strip() for part in parts),
            *(normalize_admin_name(part) for part in parts),
        }
        if item
    )


def has_scope_text(*parts: Any) -> bool:
    return bool(build_scope_haystack(*parts))


def matches_scope_text(scope: dict[str, Any], *parts: Any) -> bool:
    aliases = {token for token in scope.get("destination_aliases", set()) if token}
    if not aliases:
        return True
    normalized_haystack = build_scope_haystack(*parts)
    return any(alias in normalized_haystack for alias in aliases)
