"""后端编排层的服务工厂。"""

from __future__ import annotations

from backend.services.travel_service import TravelService


def create_travel_service() -> TravelService:
    """构建共享的旅行规划服务。"""
    return TravelService()
