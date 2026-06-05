"""Shared helpers for canonical budget-style handling."""

from __future__ import annotations


BUDGET_STYLE_ALIASES: dict[str, str] = {
    "economy": "经济",
    "经济": "经济",
    "经济实惠": "经济",
    "省钱": "经济",
    "balanced": "舒适",
    "舒适": "舒适",
    "平衡适中": "舒适",
    "适中": "舒适",
    "comfort": "品质",
    "品质": "品质",
    "舒适品质": "品质",
    "quality": "品质",
    "luxury": "高品质",
    "高品质": "高品质",
    "高端": "高品质",
    "奢华": "高品质",
}

_BUDGET_STYLE_FACTORS: dict[str, float] = {
    "经济": 0.75,
    "舒适": 1.0,
    "品质": 1.3,
    "高品质": 1.6,
}

_TICKET_WARNING_THRESHOLDS: dict[str, float] = {
    "经济": 100.0,
    "舒适": 180.0,
    "品质": 260.0,
    "高品质": 360.0,
}

_LODGING_SEARCH_KEYWORDS: dict[str, tuple[str, ...]] = {
    "经济": ("经济型酒店", "快捷酒店", "高性价比酒店", "民宿"),
    "舒适": ("舒适型酒店", "高评分酒店", "精品酒店", "民宿"),
    "品质": ("品质酒店", "高评分酒店", "豪华型酒店", "精品酒店"),
    "高品质": ("豪华型酒店", "高端酒店", "五星级酒店", "度假酒店"),
}

_LODGING_FALLBACK_TYPES: dict[str, tuple[str, str, str]] = {
    "经济": ("经济酒店", "高性价比民宿", "便捷旅舍"),
    "舒适": ("舒适酒店", "精选民宿", "便捷酒店"),
    "品质": ("品质酒店", "精品民宿", "高评分酒店"),
    "高品质": ("豪华酒店", "度假民宿", "高端酒店"),
}


def normalize_budget_style(value: str | None, default: str = "舒适") -> str:
    """Normalize budget-style aliases to one canonical label."""
    text = str(value or "").strip()
    if not text:
        return default
    return BUDGET_STYLE_ALIASES.get(text, default)


def budget_style_factor(value: str | None, default: str = "舒适") -> float:
    """Return the cost multiplier for the normalized budget style."""
    style = normalize_budget_style(value, default=default)
    return _BUDGET_STYLE_FACTORS.get(style, _BUDGET_STYLE_FACTORS[default])


def ticket_warning_threshold(value: str | None, default: str = "舒适") -> float:
    """Return the ticket-price warning threshold for the budget style."""
    style = normalize_budget_style(value, default=default)
    return _TICKET_WARNING_THRESHOLDS.get(style, _TICKET_WARNING_THRESHOLDS[default])


def lodging_search_keywords(value: str | None, default: str = "舒适") -> tuple[str, ...]:
    """Return preferred hotel-search keywords for the budget style."""
    style = normalize_budget_style(value, default=default)
    return _LODGING_SEARCH_KEYWORDS.get(style, _LODGING_SEARCH_KEYWORDS[default])


def lodging_fallback_types(value: str | None, default: str = "舒适") -> tuple[str, str, str]:
    """Return fallback hotel type labels for the budget style."""
    style = normalize_budget_style(value, default=default)
    return _LODGING_FALLBACK_TYPES.get(style, _LODGING_FALLBACK_TYPES[default])
