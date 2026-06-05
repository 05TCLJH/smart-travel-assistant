"""请求级运行时密钥上下文。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeKeys:
    amap_api_key: str = ""
    bailian_api_key: str = ""
    owner_id: str = ""


_RUNTIME_KEYS: ContextVar[RuntimeKeys] = ContextVar("runtime_keys", default=RuntimeKeys())


def _normalize_key(value: str | None) -> str:
    return str(value or "").strip()


def get_runtime_keys() -> RuntimeKeys:
    return _RUNTIME_KEYS.get()


def get_runtime_owner_id() -> str:
    return get_runtime_keys().owner_id


@contextmanager
def runtime_keys_scope(*, amap_api_key: str | None = None, bailian_api_key: str | None = None, owner_id: str | None = None):
    """在当前执行链路内临时注入用户自备 Key 与运行时会话边界。"""
    current = get_runtime_keys()
    next_keys = RuntimeKeys(
        amap_api_key=_normalize_key(amap_api_key) if amap_api_key is not None else current.amap_api_key,
        bailian_api_key=_normalize_key(bailian_api_key) if bailian_api_key is not None else current.bailian_api_key,
        owner_id=_normalize_key(owner_id) if owner_id is not None else current.owner_id,
    )
    token = _RUNTIME_KEYS.set(next_keys)
    try:
        yield next_keys
    finally:
        _RUNTIME_KEYS.reset(token)
