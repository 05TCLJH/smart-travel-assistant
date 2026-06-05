"""Ticket price helpers for estimate-only budgeting."""

from __future__ import annotations

from typing import Any


def parse_ticket_price(raw: Any) -> float | None:
    """Only treats explicit free-admission markers as a resolved price."""
    text = str(raw or "").strip()
    if not text:
        return None
    if text in {"免费", "免票"}:
        return 0.0
    return None


def match_official_ticket_source(place: str, destination: str = "") -> dict[str, Any] | None:
    """Official ticket matching is disabled in the estimate-only flow."""
    return None


def resolve_ticket_price_source(point: dict[str, Any], destination: str = "") -> dict[str, Any]:
    """Always returns estimate metadata after rolling back live verification."""
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
    """Attach estimate-only ticket metadata to a POI."""
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
