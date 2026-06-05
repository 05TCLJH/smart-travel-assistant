"""精简的流式网络传输客户端。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib import request


MCP_PROTOCOL_VERSION = "2025-06-18"


def _header_case_insensitive(headers: Any, name: str) -> str:
    target = name.lower()
    for key, value in getattr(headers, "items", lambda: [])():
        if str(key).lower() == target:
            return str(value)
    return ""


@dataclass
class StreamableHttpMcpClient:
    server_url: str
    timeout: float = 20.0
    client_name: str = "smart-travel-assistant"
    client_version: str = "1.0.0"
    session_id: str = ""
    _counter: int = 0
    _initialized: bool = False
    _cached_tools: list[dict[str, Any]] = field(default_factory=list)

    def initialize(self) -> None:
        if self._initialized:
            return
        self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"roots": {"listChanged": False}},
                "clientInfo": {"name": self.client_name, "version": self.client_version},
            },
        )
        self._notify("notifications/initialized")
        self._initialized = True

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        payload = self._request("tools/list", {})
        tools = payload.get("tools", []) if isinstance(payload, dict) else []
        self._cached_tools = tools if isinstance(tools, list) else []
        return list(self._cached_tools)

    def list_resources(self) -> list[dict[str, Any]]:
        self.initialize()
        payload = self._request("resources/list", {})
        rows = payload.get("resources", []) if isinstance(payload, dict) else []
        return rows if isinstance(rows, list) else []

    def read_resource(self, uri: str) -> dict[str, Any]:
        self.initialize()
        payload = self._request("resources/read", {"uri": uri})
        return payload if isinstance(payload, dict) else {}

    def list_prompts(self) -> list[dict[str, Any]]:
        self.initialize()
        payload = self._request("prompts/list", {})
        rows = payload.get("prompts", []) if isinstance(payload, dict) else []
        return rows if isinstance(rows, list) else []

    def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.initialize()
        payload = self._request("prompts/get", {"name": name, "arguments": arguments or {}})
        return payload if isinstance(payload, dict) else {}

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.initialize()
        payload = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if not isinstance(payload, dict):
            return {}
        structured = payload.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        if isinstance(structured, list):
            return {"items": structured}
        content = payload.get("content", [])
        if isinstance(content, list):
            texts = [str(item.get("text", "")).strip() for item in content if isinstance(item, dict) and item.get("type") == "text"]
            merged = "\n".join(text for text in texts if text)
            if merged:
                try:
                    parsed = json.loads(merged)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return {"text": merged}
        return payload

    def close(self) -> None:
        if not self.session_id:
            return
        req = request.Request(self.server_url, headers={"Mcp-Session-Id": self.session_id}, method="DELETE")
        try:
            with request.urlopen(req, timeout=self.timeout):
                pass
        except Exception:
            pass
        self.session_id = ""
        self._initialized = False

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self._post_json(body)

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._counter += 1
        body = {"jsonrpc": "2.0", "id": self._counter, "method": method, "params": params or {}}
        response = self._post_json(body)
        if "error" in response:
            error = response["error"]
            message = error.get("message", "MCP request failed") if isinstance(error, dict) else str(error)
            raise RuntimeError(message)
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def _post_json(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = request.Request(
            self.server_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            session_id = _header_case_insensitive(response.headers, "Mcp-Session-Id")
            if session_id:
                self.session_id = session_id
            content_type = _header_case_insensitive(response.headers, "Content-Type").lower()
            raw = response.read().decode("utf-8")
        if "text/event-stream" in content_type:
            return self._parse_sse_payload(raw)
        if not raw.strip():
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _parse_sse_payload(raw: str) -> dict[str, Any]:
        last_data = ""
        for line in raw.splitlines():
            if line.startswith("data:"):
                last_data = line[5:].strip()
        if not last_data:
            return {}
        parsed = json.loads(last_data)
        return parsed if isinstance(parsed, dict) else {}
