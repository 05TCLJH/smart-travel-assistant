"""用户画像接口，负责读取、更新和重置会话级画像。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.api_response import success_response
from backend.services.persona_service import PersonaService


router = APIRouter()
service = PersonaService()


class PersonaUpdateRequest(BaseModel):
    name: str | None = None
    travel_style: str | None = None
    stamina: str | None = None
    budget_style: str | None = None


@router.get("/profile")
async def get_profile() -> dict:
    return success_response(service.load(), "获取成功")


@router.put("/profile")
async def update_profile(request: PersonaUpdateRequest) -> dict:
    try:
        data = service.save(request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success_response(data, "保存成功")


@router.post("/reset")
async def reset_profile() -> dict:
    return success_response(service.reset(), "已恢复默认画像")
