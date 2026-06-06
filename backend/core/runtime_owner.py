"""匿名运行时 owner 隔离辅助函数。

本项目不需要完整登录系统，但仍需要稳定的浏览器级边界，确保任务、旅行会话和地图票据不会在不同用户之间共享。
"""

from __future__ import annotations

import uuid

from fastapi import Request, Response

from backend.core.settings import env_bool, runtime_owner_cookie_samesite, runtime_owner_trust_header


RUNTIME_OWNER_COOKIE = "smart_travel_owner"
RUNTIME_OWNER_HEADER = "x-travel-owner"
_COOKIE_MAX_AGE_SECONDS = 7 * 24 * 3600


def read_runtime_owner(request: Request) -> str:
    cookie_value = str(request.cookies.get(RUNTIME_OWNER_COOKIE, "")).strip()
    if cookie_value:
        return cookie_value
    if not runtime_owner_trust_header():
        return ""
    header_value = str(request.headers.get(RUNTIME_OWNER_HEADER, "")).strip()
    return header_value


def ensure_runtime_owner(request: Request, response: Response, owner_id: str | None = None) -> str:
    owner_id = str(owner_id or "").strip() or read_runtime_owner(request) or uuid.uuid4().hex
    samesite = runtime_owner_cookie_samesite()
    secure = env_bool("RUNTIME_OWNER_COOKIE_SECURE", request.url.scheme == "https")
    if samesite == "none":
        secure = True
    response.set_cookie(
        key=RUNTIME_OWNER_COOKIE,
        value=owner_id,
        max_age=_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite=samesite,
        secure=secure,
        path="/",
    )
    return owner_id
