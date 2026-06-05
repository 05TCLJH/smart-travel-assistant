"""System status and runtime configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.api_key_specs import (
    classify_service_failure,
    issues_to_field_map,
    list_key_specs_public,
    validate_runtime_key_updates,
)
from backend.core.api_response import failure_response, success_response
from backend.core.runtime_owner import ensure_runtime_owner
from backend.core.settings import (
    amap_enabled,
    bailian_enabled,
    get_runtime_config,
    has_backend_key_configured,
    travel_context_mcp_enabled,
)
from backend.services.vision_service import VisionService


router = APIRouter()


class RuntimeConfigPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    amap_api_key: str | None = Field(default=None, description="Amap API key")
    amap_web_service_key: str | None = Field(default=None, description="Legacy alias for amap_api_key")
    amap_mcp_api_key: str | None = Field(default=None, description="Legacy alias for amap_api_key")
    bailian_api_key: str | None = Field(default=None, description="DashScope/Bailian API key")


def _pick_amap_key(payload: RuntimeConfigPayload) -> str | None:
    for name in ("amap_api_key", "amap_mcp_api_key", "amap_web_service_key"):
        if name not in payload.model_fields_set:
            continue
        value = getattr(payload, name)
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            return cleaned
    return None


def _pick_bailian_key(payload: RuntimeConfigPayload) -> str | None:
    if "bailian_api_key" not in payload.model_fields_set:
        return None
    value = payload.bailian_api_key
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def _build_status_payload() -> dict[str, object]:
    vision_enabled = VisionService().enabled
    trip_live_enabled = amap_enabled()
    runtime_config = get_runtime_config()
    mode = "hybrid" if has_backend_key_configured() else "demo"

    notes = [
        "本次会话填写的密钥只保存在当前浏览器中，执行任务时才会临时带入运行链路，不会写入长期后端配置。",
        "排队中的行程任务运行在共享运行时状态中，因此进度流和结果查询不依赖单个请求进程。",
        "当前部署形态面向单个公网实例，适合 Hugging Face Space 这类短时运行状态环境。",
    ]
    if mode == "demo":
        notes.append("实时地图和景点识别能力需要你在当前会话中提供自己的密钥。")
    else:
        notes.append("后端环境变量中的密钥仍可作为兜底，但当前会话填写的密钥会优先生效。")
    if trip_live_enabled:
        notes.append("已检测到可用高德能力，地图、天气和 POI 会优先走实时服务。")
    else:
        notes.append("高德实时能力未启用，地图和天气可能会回退到本地或演示数据。")
    if travel_context_mcp_enabled():
        notes.append("Travel Context MCP 已启用，并受部署级鉴权与运行时隔离保护。")
    else:
        notes.append("Travel Context MCP 默认关闭，以避免暴露内部规划上下文。")
    if vision_enabled:
        notes.append("景点识别能力已启用。")
    else:
        notes.append("尚未检测到可用百炼密钥，景点识别能力暂不可用。")
    return {
        "app_mode": mode,
        "trip_live_enabled": trip_live_enabled,
        "amap_enabled": amap_enabled(),
        "direct_amap_enabled": amap_enabled(),
        "bailian_enabled": bailian_enabled(),
        "vision_enabled": vision_enabled,
        "llm_enabled": vision_enabled,
        "report_enabled": True,
        "runtime_config": runtime_config,
        "notes": notes,
    }


@router.put("/runtime-config")
async def save_runtime_config(payload: RuntimeConfigPayload) -> dict:
    amap_value = _pick_amap_key(payload)
    bailian_value = _pick_bailian_key(payload)

    if amap_value is None and bailian_value is None:
        return success_response(
            {"runtime_config": get_runtime_config(), "session_only": True},
            "会话密钥校验完成，密钥不会写入长期后端配置。",
        )

    validation_issues = validate_runtime_key_updates(
        amap_api_key=amap_value if amap_value is not None else None,
        bailian_api_key=bailian_value if bailian_value is not None else None,
    )
    if validation_issues:
        return failure_response(
            {
                "runtime_config": get_runtime_config(),
                "validation_errors": issues_to_field_map(validation_issues),
            },
            "密钥格式校验未通过。",
        )

    updated: list[str] = []
    if amap_value is not None:
        updated.append("amap")
    if bailian_value is not None:
        updated.append("bailian")

    return success_response(
        {
            "runtime_config": get_runtime_config(),
            "session_only": True,
            "validated": updated,
        },
        f"已完成校验：{', '.join(updated)}",
    )


@router.get("/status")
async def status(request: Request) -> JSONResponse:
    response = JSONResponse(success_response(_build_status_payload(), "系统状态已加载"))
    ensure_runtime_owner(request, response)
    return response


@router.get("/runtime-config")
async def runtime_config() -> dict:
    return success_response(get_runtime_config(), "运行时配置已加载")


@router.get("/key-specs")
async def key_specs() -> dict:
    return success_response({"specs": list_key_specs_public()}, "密钥规范已加载")


@router.get("/progress-catalog")
async def progress_catalog() -> dict:
    from backend.runtime.progress_catalog import list_steps_public

    return success_response({"steps": list_steps_public()}, "进度目录已加载")


@router.post("/classify-failure")
async def classify_failure(payload: dict) -> dict:
    message = str(payload.get("message", "")).strip()
    hint = str(payload.get("hint", "")).strip()
    return success_response(classify_service_failure(message, hint=hint or None), "ok")
