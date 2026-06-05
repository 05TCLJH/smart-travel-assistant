"""Service factories for backend orchestration layers."""

from __future__ import annotations

from backend.services.travel_service import TravelService


def create_travel_service() -> TravelService:
    """Build the shared travel planning service."""
    return TravelService()
