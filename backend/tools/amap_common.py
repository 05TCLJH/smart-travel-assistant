"""高德工具通用基础模块。

集中放置数值转换和错误提示等无状态公共能力，供地图、天气、路线等子模块复用。
"""

from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    """将输入安全转换为浮点数，失败时返回默认值。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """将输入安全转换为整数，失败时返回默认值。"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def amap_failure_followup_hint(message: str) -> str:
    """生成高德接口失败后的补充排查提示。"""
    text = str(message or "")
    lower = text.lower()
    if any(key in text for key in ("配额", "额度", "限流", "QPS", "qps", "调用量", "CUQPS", "访问过快", "并发", "超限")):
        return " 这通常与高德开放平台「日调用量 / 并发 QPS / 套餐额度」或 Key 类型不匹配有关，请到控制台查看用量、账单与错误码说明，或更换 MCP/Web 服务专用 Key 后重试。"
    if any(key in text for key in ("10044", "10045", "10046", "10041", "10042", "INVALID_USER_KEY", "USERKEY", "USER_KEY")):
        return " 请核对 Key 是否开通对应服务、是否与当前 MCP 域名/调用方式匹配。"
    if any(key in lower for key in ("quota", "daily", "limit exceeded", "rate limit")):
        return " 接口返回与调用配额或频控相关，可稍后再试或提升配额。"
    return " 若 Key 与网络正常仍失败，请检查 MCP 服务地址与后端日志中的完整错误信息。"
