"""景点识别接口，负责上传图片并返回识别结果。"""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.core.api_response import success_response
from backend.core.runtime_context import runtime_keys_scope
from backend.services.vision_service import VisionService


router = APIRouter()


def _parse_persona_form(persona: str | None) -> dict:
    """表单画像字段允许为空或格式错误，避免无效 JSON 直接变成 500。"""
    if not persona or not str(persona).strip():
        return {}
    try:
        data = json.loads(persona)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


@router.post("/recognize")
async def recognize(
    file: UploadFile = File(...),
    persona: str | None = Form(None),
    amap_api_key: str | None = Form(None),
    bailian_api_key: str | None = Form(None),
) -> dict:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")

    with runtime_keys_scope(
        amap_api_key=str(amap_api_key or "").strip() or None,
        bailian_api_key=str(bailian_api_key or "").strip() or None,
    ):
        service = VisionService()
        if not service.enabled:
            raise HTTPException(
                status_code=503,
                detail="当前环境未配置图片识别所需的 Bailian 或 Qwen Key。",
            )

        try:
            image_bytes = await file.read()
            payload = _parse_persona_form(persona)
            result = service.recognize(image_bytes, file.content_type or "image/jpeg", payload)
            return success_response(result, "识别完成")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"识别失败：{exc}") from exc
