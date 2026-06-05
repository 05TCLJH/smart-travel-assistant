"""环境与运行时配置。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv, set_key, unset_key

from backend.core.runtime_context import get_runtime_keys
from backend.core.paths import PROJECT_ROOT


ENV_FILE_PATH = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=ENV_FILE_PATH)

AMAP_API_KEY_NAME = "AMAP_API_KEY"
# 仅用于读取旧配置并自动合并到高德接口密钥，新配置请勿再使用
_LEGACY_AMAP_KEY_NAMES = ("AMAP_MCP_API_KEY", "AMAP_MAPS_API_KEY", "AMAP_WEB_SERVICE_KEY")
BAILIAN_ENV_NAMES = ("ALIYUN_BAILIAN_API_KEY", "DASHSCOPE_API_KEY", "BAILIAN_API_KEY")
PRIMARY_BAILIAN_ENV_NAME = BAILIAN_ENV_NAMES[0]


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on", "y"}:
        return True
    if raw in {"0", "false", "no", "off", "n"}:
        return False
    return default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def public_api_base_url() -> str:
    return first_env("PUBLIC_API_BASE_URL", "API_BASE_URL")


def cors_allowed_origins() -> list[str]:
    return env_list("CORS_ALLOW_ORIGINS")


def cors_allow_origin_regex() -> str:
    return first_env("CORS_ALLOW_ORIGIN_REGEX")


def runtime_owner_cookie_samesite() -> str:
    raw = first_env("RUNTIME_OWNER_COOKIE_SAMESITE").strip().lower()
    if raw in {"lax", "strict", "none"}:
        return raw
    return "lax"


def runtime_owner_trust_header() -> bool:
    return env_bool("RUNTIME_OWNER_TRUST_HEADER", False)


def trip_sync_route_enabled() -> bool:
    return env_bool("TRIP_SYNC_ROUTE_ENABLED", False)


def runtime_state_db_path() -> Path | None:
    raw = first_env("RUNTIME_STATE_DB_PATH")
    if not raw:
        return None
    return Path(raw).expanduser()


def runtime_task_lease_seconds() -> float:
    return max(30.0, env_float("RUNTIME_TASK_LEASE_SECONDS", 300.0))


def runtime_task_poll_seconds() -> float:
    return max(0.2, env_float("RUNTIME_TASK_POLL_SECONDS", 0.8))


def runtime_task_max_attempts() -> int:
    return max(1, env_int("RUNTIME_TASK_MAX_ATTEMPTS", 2))


def amap_key() -> str:
    """当前链路可用的高德 Key，优先使用请求级注入，其次使用环境变量。"""
    runtime_key = get_runtime_keys().amap_api_key
    if runtime_key:
        return runtime_key
    return first_env(AMAP_API_KEY_NAME, *_LEGACY_AMAP_KEY_NAMES)


def amap_enabled() -> bool:
    return env_bool("AMAP_MCP_ENABLED", True) and bool(first_env("AMAP_MCP_SERVER_URL") or amap_key())


def bailian_key() -> str:
    runtime_key = get_runtime_keys().bailian_api_key
    if runtime_key:
        return runtime_key
    return first_env(*BAILIAN_ENV_NAMES)


def bailian_enabled() -> bool:
    return bool(bailian_key())


def travel_context_mcp_enabled() -> bool:
    return env_bool("TRAVEL_CONTEXT_MCP_ENABLED", False)


def travel_context_mcp_token() -> str:
    return first_env("TRAVEL_CONTEXT_MCP_TOKEN")


def _mask_secret(value: str) -> str:
    secret = value.strip()
    if not secret:
        return ""
    if len(secret) <= 6:
        return "*" * len(secret)
    if len(secret) <= 12:
        return f"{secret[:2]}{'*' * (len(secret) - 4)}{secret[-2:]}"
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


def _ensure_env_file() -> Path:
    ENV_FILE_PATH.touch(exist_ok=True)
    return ENV_FILE_PATH


def _persist_env_value(name: str, value: str) -> None:
    env_path = _ensure_env_file()
    cleaned_value = value.strip()
    if cleaned_value:
        set_key(str(env_path), name, cleaned_value, quote_mode="never", encoding="utf-8")
    else:
        unset_key(str(env_path), name, quote_mode="never", encoding="utf-8")


def _set_runtime_env(name: str, value: str) -> None:
    cleaned_value = value.strip()
    if cleaned_value:
        os.environ[name] = cleaned_value
    else:
        os.environ.pop(name, None)


def _clear_legacy_amap_keys() -> None:
    for legacy_name in _LEGACY_AMAP_KEY_NAMES:
        _set_runtime_env(legacy_name, "")
        _persist_env_value(legacy_name, "")


def consolidate_amap_env_keys() -> None:
    """启动时将旧版多个高德 Key 变量合并为 AMAP_API_KEY。"""
    if first_env(AMAP_API_KEY_NAME):
        return
    legacy_value = first_env(*_LEGACY_AMAP_KEY_NAMES)
    if not legacy_value:
        return
    _set_runtime_env(AMAP_API_KEY_NAME, legacy_value)
    _persist_env_value(AMAP_API_KEY_NAME, legacy_value)
    _clear_legacy_amap_keys()


def has_backend_key_configured() -> bool:
    return bool(first_env("AMAP_MCP_SERVER_URL") or first_env(AMAP_API_KEY_NAME, *_LEGACY_AMAP_KEY_NAMES) or first_env(*BAILIAN_ENV_NAMES))


def get_runtime_config() -> dict[str, object]:
    key = first_env(AMAP_API_KEY_NAME, *_LEGACY_AMAP_KEY_NAMES)
    amap_mcp_url = first_env("AMAP_MCP_SERVER_URL")
    bailian_secret = first_env(*BAILIAN_ENV_NAMES)
    return {
        "amap_configured": bool(key),
        "amap_mcp_url_configured": bool(amap_mcp_url),
        "bailian_configured": bool(bailian_secret),
        "travel_context_mcp_enabled": travel_context_mcp_enabled(),
        "amap_key_masked": _mask_secret(key),
        "amap_mcp_url_masked": _mask_secret(amap_mcp_url),
        "bailian_key_masked": _mask_secret(bailian_secret),
        "config_source": "backend-env",
        "mode": "hybrid" if has_backend_key_configured() else "demo",
        "runtime_only": False,
        "public_api_base_url": public_api_base_url(),
        "cors_allow_origins": cors_allowed_origins(),
        "cors_allow_origin_regex": cors_allow_origin_regex(),
        "runtime_state_db_path": str(runtime_state_db_path() or ""),
        "runtime_task_lease_seconds": runtime_task_lease_seconds(),
    }


def update_runtime_config(
    *,
    amap_api_key: str | None = None,
    amap_mcp_server_url: str | None = None,
    bailian_api_key: str | None = None,
) -> dict[str, object]:
    """兼容旧接口；BYOK 模式下不再写入后端运行时配置。"""
    _ = (amap_api_key, amap_mcp_server_url, bailian_api_key)
    return get_runtime_config()
