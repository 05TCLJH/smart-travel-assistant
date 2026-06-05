"""高德官方服务的高层封装。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import threading
import time
from typing import Any
from urllib import parse

from backend.core.settings import amap_key, env_float, env_int, first_env
from backend.mcp.streamable_http_client import StreamableHttpMcpClient


def _quota_or_rate_limited(exc: BaseException) -> bool:
    msg = str(exc)
    return any(
        token in msg
        for token in (
            "CUQPS",
            "QPS",
            "限流",
            "访问过快",
            "配额",
            "too many requests",
            "RATE_LIMIT",
        )
    )


AMAP_MCP_TOOL_ALIASES = {
    "maps_text_search": ("maps_text_search", "text_search", "poi_search"),
    "maps_around_search": ("maps_around_search", "around_search", "poi_around_search"),
    "maps_search_detail": ("maps_search_detail", "search_detail", "poi_detail"),
    "maps_regeocode": ("maps_regeocode", "regeocode"),
    "maps_geocode": ("maps_geo", "maps_geocode", "geocode"),
    "maps_weather": ("maps_weather", "weather"),
    "maps_distance": ("maps_distance", "distance"),
    "maps_direction_driving": ("maps_direction_driving", "driving_route", "maps_driving_route"),
    "maps_direction_walking": ("maps_direction_walking", "walking_route", "maps_walking_route"),
    "maps_direction_transit_integrated": ("maps_direction_transit_integrated", "transit_route", "maps_transit_route"),
}


@dataclass
class AmapMcpClient:
    timeout: float = field(default_factory=lambda: env_float("AMAP_MCP_TIMEOUT_SECONDS", 20.0))
    _client: StreamableHttpMcpClient | None = None
    _client_server_url: str = ""
    _tool_names: dict[str, str] = field(default_factory=dict)
    _response_cache: dict[str, tuple[float, float, dict[str, Any]]] = field(default_factory=dict)
    _call_gate: threading.Semaphore = field(default_factory=lambda: threading.Semaphore(env_int("AMAP_MCP_MAX_CONCURRENT_CALLS", 2)), repr=False)
    _call_gap_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _last_call_mono: float = field(default=0.0, repr=False)

    @property
    def enabled(self) -> bool:
        return bool(self.server_url)

    @property
    def server_url(self) -> str:
        configured = first_env("AMAP_MCP_SERVER_URL")
        if configured:
            return configured
        key = amap_key()
        if not key:
            return ""
        query = parse.urlencode({"key": key})
        return f"https://mcp.amap.com/mcp?{query}"

    @property
    def client(self) -> StreamableHttpMcpClient:
        current_server_url = self.server_url
        if self._client is not None and self._client_server_url != current_server_url:
            self.close()
        if self._client is None:
            if not self.enabled:
                raise RuntimeError("Amap MCP is not configured")
            self._client_server_url = current_server_url
            self._client = StreamableHttpMcpClient(server_url=current_server_url, timeout=self.timeout, client_name="smart-travel-assistant", client_version="2.0.0")
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None
        self._client_server_url = ""
        self._tool_names.clear()
        self._response_cache.clear()

    def geocode(self, address: str) -> dict[str, Any]:
        return self._call("maps_geocode", {"address": address})

    def regeocode(self, location: str) -> dict[str, Any]:
        return self._call("maps_regeocode", {"location": location})

    def weather(self, city: str, extensions: str = "all") -> dict[str, Any]:
        return self._call("maps_weather", {"city": city})

    def text_search(
        self,
        keywords: str,
        city: str = "",
        types: str = "",
        *,
        page: int = 1,
        offset: int = 20,
        children: bool = False,
        extensions: str = "all",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"keywords": keywords}
        if city:
            payload["city"] = city
            payload["citylimit"] = True
        if types:
            payload["types"] = types
        if page > 0:
            payload["page"] = page
        if offset > 0:
            payload["offset"] = offset
        if children:
            payload["children"] = 1
        if extensions:
            payload["extensions"] = extensions
        return self._call("maps_text_search", payload)

    def around_search(self, keywords: str, location: str, radius: int = 3000, types: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {"keywords": keywords, "location": location, "radius": str(radius)}
        if types:
            payload["types"] = types
        return self._call("maps_around_search", payload)

    def search_detail(self, poi_id: str) -> dict[str, Any]:
        return self._call("maps_search_detail", {"id": poi_id})

    def distance(self, origins: str, destination: str, route_type: str = "1") -> dict[str, Any]:
        return self._call("maps_distance", {"origins": origins, "destination": destination, "type": route_type})

    def driving_route(self, origin: str, destination: str, waypoints: list[str] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"origin": origin, "destination": destination}
        if waypoints:
            payload["waypoints"] = ";".join(item for item in waypoints if item)
        return self._call("maps_direction_driving", payload)

    def walking_route(self, origin: str, destination: str) -> dict[str, Any]:
        return self._call("maps_direction_walking", {"origin": origin, "destination": destination})

    def transit_route(self, origin: str, destination: str, city: str, cityd: str = "") -> dict[str, Any]:
        payload = {"origin": origin, "destination": destination, "city": city}
        if cityd:
            payload["cityd"] = cityd
        return self._call("maps_direction_transit_integrated", payload)

    def _call(self, alias: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_name = self._resolve_tool_name(alias)
        cache_key = json.dumps({"server_url": self.server_url, "tool": tool_name, "arguments": arguments}, ensure_ascii=False, sort_keys=True)
        now = time.monotonic()
        cached = self._response_cache.get(cache_key)
        if cached:
            ts, ttl, body = cached
            if now - ts <= ttl:
                return deepcopy(body)

        min_gap = env_float("AMAP_MCP_MIN_INTERVAL_SECONDS", 0.08)
        retry_sleep = env_float("AMAP_MCP_QUOTA_RETRY_SECONDS", 2.8)
        weather_ttl = env_float("AMAP_MCP_WEATHER_CACHE_SECONDS", 900.0)
        default_ttl = env_float("AMAP_MCP_DEFAULT_CACHE_SECONDS", 300.0)
        ttl = weather_ttl if "weather" in tool_name.lower() else default_ttl

        def invoke_once() -> dict[str, Any]:
            payload = self.client.call_tool(tool_name, arguments)
            if isinstance(payload, dict):
                text = str(payload.get("text", "")).strip()
                if text.startswith("API 调用失败：") or text.startswith("调用失败："):
                    raise RuntimeError(text)
            return payload

        with self._call_gap_lock:
            wait = min_gap - (time.monotonic() - self._last_call_mono)
            if wait > 0:
                time.sleep(wait)
            self._last_call_mono = time.monotonic()

        with self._call_gate:
            try:
                payload = invoke_once()
            except RuntimeError as exc:
                if _quota_or_rate_limited(exc):
                    time.sleep(retry_sleep)
                    payload = invoke_once()
                else:
                    raise

        if isinstance(payload, dict):
            store_ts = time.monotonic()
            self._response_cache[cache_key] = (store_ts, ttl, deepcopy(payload))
            if len(self._response_cache) > 256:
                oldest_key = min(self._response_cache.items(), key=lambda item: item[1][0])[0]
                self._response_cache.pop(oldest_key, None)
        return payload

    def _resolve_tool_name(self, alias: str) -> str:
        if alias in self._tool_names:
            return self._tool_names[alias]
        tools = self.client.list_tools()
        names = [str(item.get("name", "")).strip() for item in tools if isinstance(item, dict)]
        candidates = AMAP_MCP_TOOL_ALIASES.get(alias, (alias,))
        for candidate in candidates:
            if candidate in names:
                self._tool_names[alias] = candidate
                return candidate
        normalized = {name.lower().replace("-", "_"): name for name in names}
        for candidate in candidates:
            key = candidate.lower().replace("-", "_")
            if key in normalized:
                self._tool_names[alias] = normalized[key]
                return normalized[key]
        raise RuntimeError(f"Amap MCP tool not found for alias: {alias}")
