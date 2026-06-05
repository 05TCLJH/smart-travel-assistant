"""统一的接口响应结构，避免各路由重复手写成功或失败返回体。"""

from __future__ import annotations

from typing import Any


def success_response(
    data: Any = None,
    message: str = "操作成功",
    **extra: Any,
) -> dict[str, Any]:
    """构造标准成功响应。"""
    payload = {
        "success": True,
        "data": data,
        "message": message,
    }
    if extra:
        payload.update(extra)
    return payload


def failure_response(
    data: Any = None,
    message: str = "操作失败",
    **extra: Any,
) -> dict[str, Any]:
    """构造标准失败响应。"""
    payload = {
        "success": False,
        "data": data,
        "message": message,
    }
    if extra:
        payload.update(extra)
    return payload
