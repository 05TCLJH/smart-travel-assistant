"""对外部网络接口的统一提交客户端，负责可重试的网络错误处理。

系统自带的旧式联网方式在 Windows 和代理环境下处理大体积结构化负载时，
容易出现连接意外中断，因此视觉识别等模块应统一使用本模块。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _is_retriable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError)):
        return True
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "unexpected_eof",
            "eof occurred",
            "connection reset",
            "connection aborted",
            "broken pipe",
            "temporarily unavailable",
        )
    )


def format_http_error(exc: BaseException, *, service: str = "远程服务") -> str:
    text = str(exc).lower()
    if "unexpected_eof" in text or "eof occurred" in text:
        return (
            f"与{service}的连接在传输时被中断（SSL/TLS EOF）。"
            "常见原因：图片过大、公司代理/防火墙截断、或网络不稳定。"
            "请将图片压缩到 4MB 以内（建议 JPG）后重试。"
        )
    if isinstance(exc, httpx.TimeoutException) or "timeout" in text or "timed out" in text:
        return f"连接{service}超时，请稍后重试或缩小上传图片。"
    if "certificate" in text or "ssl" in text:
        return f"与{service}的 HTTPS 证书校验失败，请检查系统时间、代理或企业网关设置。"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = ""
        try:
            body = exc.response.text[:200]
        except Exception:
            pass
        return f"{service}返回 HTTP {status}" + (f"：{body}" if body else "")
    return f"{service}请求失败：{exc}"


def post_json(
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float | None = None,
    max_retries: int | None = None,
    service_name: str = "远程服务",
) -> dict[str, Any]:
    """POST JSON 并解析响应为 dict；对瞬时 SSL/连接错误自动重试。"""
    timeout_seconds = timeout if timeout is not None else _env_float("HTTP_CLIENT_TIMEOUT_SECONDS", 90.0)
    retries = max_retries if max_retries is not None else _env_int("HTTP_CLIENT_MAX_RETRIES", 3)
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    timeout_cfg = httpx.Timeout(timeout_seconds, connect=min(20.0, timeout_seconds))

    last_exc: BaseException | None = None
    for attempt in range(max(1, retries)):
        try:
            with httpx.Client(timeout=timeout_cfg, http2=False, follow_redirects=True) as client:
                response = client.post(url, headers=headers, content=payload)
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"{service_name}返回非 JSON 对象")
            return data
        except BaseException as exc:
            last_exc = exc
            if attempt >= retries - 1 or not _is_retriable(exc):
                break
            time.sleep(min(4.0, 0.6 * (2**attempt)))

    assert last_exc is not None
    raise RuntimeError(format_http_error(last_exc, service=service_name)) from last_exc
