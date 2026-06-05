"""接口密钥格式规范（前后端共享校验逻辑的单一来源）。

参考：
- 高德开放平台 Key：https://lbs.amap.com/api/webservice/guide/create-project/get-key
- 阿里云百炼 / DashScope API-KEY：https://help.aliyun.com/zh/model-studio/get-api-key
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ApiKeySpec:
    id: str
    label: str
    env_names: tuple[str, ...]
    pattern: str
    format_hint: str
    doc_url: str
    min_length: int
    max_length: int

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "pattern": self.pattern,
            "format_hint": self.format_hint,
            "doc_url": self.doc_url,
            "min_length": self.min_length,
            "max_length": self.max_length,
        }


@dataclass(frozen=True)
class KeyValidationIssue:
    field: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


AMAP_KEY_SPEC = ApiKeySpec(
    id="amap_api_key",
    label="高德地图 Key",
    env_names=("AMAP_API_KEY",),
    # 高德网页服务接口密钥为 32 位十六进制字符串（与控制台展示形态一致）
    pattern=r"^[0-9a-fA-F]{32}$",
    format_hint="32 位十六进制字符（仅 0-9、a-f），无空格与引号",
    doc_url="https://lbs.amap.com/api/webservice/guide/create-project/get-key",
    min_length=32,
    max_length=32,
)

BAILIAN_KEY_SPEC = ApiKeySpec(
    id="bailian_api_key",
    label="百炼 / DashScope API Key",
    env_names=("ALIYUN_BAILIAN_API_KEY", "DASHSCOPE_API_KEY", "BAILIAN_API_KEY"),
    pattern=r"^sk-[0-9a-fA-F]{32}$",
    format_hint="以 sk- 开头，后接 32 位十六进制（示例：sk-xxxxxxxx…）",
    doc_url="https://help.aliyun.com/zh/model-studio/get-api-key",
    min_length=35,
    max_length=35,
)

KEY_SPECS: dict[str, ApiKeySpec] = {
    AMAP_KEY_SPEC.id: AMAP_KEY_SPEC,
    BAILIAN_KEY_SPEC.id: BAILIAN_KEY_SPEC,
}


def list_key_specs_public() -> list[dict[str, Any]]:
    return [spec.to_public_dict() for spec in KEY_SPECS.values()]


def _normalize_raw(value: str) -> str:
    return str(value or "")


def _field_display_name(spec: ApiKeySpec) -> str:
    if spec.id == AMAP_KEY_SPEC.id:
        return "高德地图 Key"
    if spec.id == BAILIAN_KEY_SPEC.id:
        return "DashScope API Key"
    return spec.label


def _empty_message(spec: ApiKeySpec) -> str:
    return f"{_field_display_name(spec)} 未填写，请补充。"


def _format_message(spec: ApiKeySpec) -> str:
    if spec.id == AMAP_KEY_SPEC.id:
        return "高德地图 Key 格式不正确，请检查是否包含空格、引号或复制不完整。"
    if spec.id == BAILIAN_KEY_SPEC.id:
        return "DashScope API Key 格式不正确，请检查是否以 sk- 开头，以及后续字符长度和内容是否正确。"
    return f"{_field_display_name(spec)} 格式不正确，请检查后重试。"


def validate_api_key(spec: ApiKeySpec, value: str) -> KeyValidationIssue | None:
    cleaned = _normalize_raw(value)
    trimmed = cleaned.strip()
    if not trimmed:
        return KeyValidationIssue(spec.id, "empty", _empty_message(spec))
    if cleaned != trimmed or '"' in cleaned or "'" in cleaned or re.search(r"\s", cleaned):
        return KeyValidationIssue(spec.id, "invalid_format", _format_message(spec))
    if len(cleaned) < spec.min_length or len(cleaned) > spec.max_length:
        return KeyValidationIssue(spec.id, "invalid_format", _format_message(spec))
    if not re.fullmatch(spec.pattern, cleaned):
        return KeyValidationIssue(spec.id, "invalid_format", _format_message(spec))
    return None


def validate_runtime_key_updates(
    *,
    amap_api_key: str | None = None,
    bailian_api_key: str | None = None,
) -> list[KeyValidationIssue]:
    """仅校验本次提交的字段（非 None 表示用户要更新该项）。"""
    issues: list[KeyValidationIssue] = []
    if amap_api_key is not None:
        issue = validate_api_key(AMAP_KEY_SPEC, amap_api_key)
        if issue:
            issues.append(issue)
    if bailian_api_key is not None:
        issue = validate_api_key(BAILIAN_KEY_SPEC, bailian_api_key)
        if issue:
            issues.append(issue)
    return issues


def issues_to_field_map(issues: list[KeyValidationIssue]) -> dict[str, dict[str, str]]:
    return {item.field: item.to_dict() for item in issues}


def classify_service_failure(message: str, *, hint: str | None = None) -> dict[str, str]:
    """将运行时错误文案归类为可展示的 Key / 配额提示（行程、识别、地图共用）。"""
    text = f"{message or ''} {hint or ''}".strip()
    lower = text.lower()

    if any(token in text for token in ("INVALID_USER_KEY", "USERKEY", "USER_KEY", "10001", "10002", "10003")) or (
        "invalid" in lower and "key" in lower and "amap" in lower
    ):
        return {
            "service": "amap",
            "code": "amap_key_invalid",
            "title": "高德 Key 不可用",
            "message": "高德地图 Key 格式正确，但当前不可用，请检查权限、服务开通状态或额度。",
            "doc_url": AMAP_KEY_SPEC.doc_url,
        }

    if any(token in text for token in ("配额", "额度", "限流", "QPS", "CUQPS", "调用量", "超限", "10044", "10045", "10046")) or any(
        token in lower for token in ("quota", "rate limit", "limit exceeded")
    ):
        return {
            "service": "amap",
            "code": "amap_quota",
            "title": "高德调用受限",
            "message": "高德地图 Key 格式正确，但当前不可用，请检查权限、服务开通状态或额度。",
            "doc_url": AMAP_KEY_SPEC.doc_url,
        }

    if any(token in lower for token in ("dashscope", "bailian", "aliyun")) and any(
        token in lower for token in ("api key", "apikey", "invalid", "unauthorized", "401", "403")
    ):
        return {
            "service": "bailian",
            "code": "bailian_key_invalid",
            "title": "百炼 Key 不可用",
            "message": "DashScope API Key 格式正确，但当前不可用，请检查是否有效、是否已失效、是否有权限或是否已超出额度。",
            "doc_url": BAILIAN_KEY_SPEC.doc_url,
        }

    if any(token in text for token in ("未配置", "未启用", "not configured", "disabled")) and any(
        token in lower for token in ("bailian", "vision", "识别", "dashscope")
    ):
        return {
            "service": "bailian",
            "code": "bailian_not_configured",
            "title": "百炼 Key 未配置",
            "message": "DashScope API Key 暂时无法验证可用性，请稍后重试。",
            "doc_url": BAILIAN_KEY_SPEC.doc_url,
        }

    if any(token in lower for token in ("unexpected_eof", "eof occurred", "ssl/tls eof")) or (
        "ssl" in lower and "eof" in lower
    ):
        return {
            "service": "bailian",
            "code": "bailian_network_ssl",
            "title": "视觉模型连接中断",
            "message": "与 DashScope 的 HTTPS 连接在传输时被中断。请将图片压缩到 4MB 以内（建议 JPG）、检查代理/防火墙，或稍后重试。",
            "doc_url": BAILIAN_KEY_SPEC.doc_url,
        }

    if any(token in text for token in ("未配置高德", "体验模式", "演示数据", "demo-local", "MCP 未")):
        return {
            "service": "amap",
            "code": "amap_not_configured",
            "title": "高德 Key 未生效",
            "message": "当前路线/景点可能使用演示数据。请配置有效的高德 Key 后重新生成。",
            "doc_url": AMAP_KEY_SPEC.doc_url,
        }

    return {
        "service": "unknown",
        "code": "unknown",
        "title": "无法验证可用性",
        "message": f"{text}。暂时无法验证可用性，请稍后重试。" if text else "暂时无法验证可用性，请稍后重试。",
        "doc_url": "",
    }
