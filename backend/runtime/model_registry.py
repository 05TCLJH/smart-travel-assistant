"""阿里云百炼兼容大模型注册表。"""

from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI

from backend.core.settings import bailian_key, first_env


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_CHAT_MODEL = "qwen-plus"
DEFAULT_TIMEOUT_SECONDS = 20


def llm_available() -> bool:
    return bool(bailian_key())


def get_chat_model(*, model: str | None = None, temperature: float = 0.15, **kwargs: Any) -> ChatOpenAI | None:
    if not llm_available():
        return None

    timeout_seconds = int(os.getenv("LLM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)).strip() or DEFAULT_TIMEOUT_SECONDS)
    max_retries = int(os.getenv("LLM_MAX_RETRIES", "1").strip() or 1)

    return ChatOpenAI(
        api_key=bailian_key(),
        base_url=first_env("ALIYUN_BAILIAN_BASE_URL") or DEFAULT_BASE_URL,
        model=model or os.getenv("LLM_MODEL", "").strip() or DEFAULT_CHAT_MODEL,
        temperature=temperature,
        timeout=timeout_seconds,
        max_retries=max_retries,
        **kwargs,
    )
