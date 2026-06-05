"""Runtime client helpers.

Travel planning services are now created per task/request, so there is no
process-wide Amap client cache to reset.
"""

from __future__ import annotations


def reset_cached_amap_clients() -> None:
    """Retained for compatibility with older call sites."""
    return None
