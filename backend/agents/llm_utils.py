"""面向落地校验决策的共享模型辅助函数。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage


def extract_json(text: Any) -> str:
    content = str(text or "").strip()
    if content.startswith("{") and content.endswith("}"):
        return content
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        return content[start : end + 1]
    return "{}"


def invoke_structured_json(runtime, system_prompt: str, payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if getattr(runtime, "chat_model", None) is None:
        return fallback
    if hasattr(runtime, "check_cancelled"):
        runtime.check_cancelled()
    try:
        response = runtime.chat_model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            ]
        )
        result = json.loads(extract_json(response.content))
        return result if isinstance(result, dict) else fallback
    except Exception:
        return fallback


def invoke_brief(runtime, system_prompt: str, payload: dict[str, Any], fallback: str = "") -> str:
    if getattr(runtime, "chat_model", None) is None:
        return fallback
    if hasattr(runtime, "check_cancelled"):
        runtime.check_cancelled()
    try:
        response = runtime.chat_model.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            ]
        )
        text = str(response.content or "").strip()
        return text[:240] if text else fallback
    except Exception:
        return fallback
