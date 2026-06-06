"""预算估算模式下的票价辅助函数。"""

from __future__ import annotations

from typing import Any


def parse_ticket_price(raw: Any) -> float | None:
    """只把明确的免票标记视为已解析价格。"""
    text = str(raw or "").strip()
    if not text:
        return None
    if text in {"免费", "免票"}:
        return 0.0
    return None


def match_official_ticket_source(place: str, destination: str = "") -> dict[str, Any] | None:
    """仅估算流程中不再做正式票务匹配。"""
    return None


def resolve_ticket_price_source(point: dict[str, Any], destination: str = "") -> dict[str, Any]:
    """回退实时校验后，始终返回估算元数据。"""
    return {
        "price": None,
        "source_type": "estimated",
        "source_label": "经验估算",
        "source_name": "",
        "source_url": "",
        "booking_note": "",
        "last_verified_at": "",
    }


def attach_ticket_reference(poi: dict[str, Any], destination: str = "") -> dict[str, Any]:
    """为 POI 附加仅估算的票务元数据。"""
    enriched = dict(poi)
    ticket_source = resolve_ticket_price_source(enriched, destination)
    enriched["ticket_source_type"] = ticket_source["source_type"]
    enriched["ticket_source_label"] = ticket_source["source_label"]
    enriched["ticket_source_name"] = ticket_source["source_name"]
    enriched["ticket_source_url"] = ticket_source["source_url"]
    enriched["ticket_booking_note"] = ticket_source["booking_note"]
    enriched["ticket_last_verified_at"] = ticket_source["last_verified_at"]
    enriched.pop("ticket_reference_price", None)
    return enriched
