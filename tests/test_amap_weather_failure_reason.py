from __future__ import annotations

from backend.core.runtime_context import runtime_keys_scope
from backend.tools.amap_tools import TravelResearchTools


def test_weather_fallback_keeps_quota_reason_when_runtime_key_is_present(monkeypatch):
    monkeypatch.setenv("AMAP_MCP_ENABLED", "false")
    monkeypatch.delenv("AMAP_MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("AMAP_API_KEY", raising=False)
    monkeypatch.delenv("AMAP_MCP_API_KEY", raising=False)
    monkeypatch.delenv("AMAP_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("AMAP_WEB_SERVICE_KEY", raising=False)

    tools = TravelResearchTools()

    def fake_geocode(_query: str) -> dict[str, object]:
        return {"city": "上海", "location": "121.47,31.23"}

    def fake_weather(_city: str, _extensions: str = "all") -> dict[str, object]:
        raise RuntimeError("QPS exceeded")

    monkeypatch.setattr(tools.amap, "geocode", fake_geocode)
    monkeypatch.setattr(tools.amap, "weather", fake_weather)

    with runtime_keys_scope(amap_api_key="0123456789abcdef0123456789abcdef"):
        payload = tools.build_weather("上海", ["2026-06-05"])

    assert payload["provider"] == "fallback"
    assert payload["is_fallback"] is True
    assert "高德调用受限" in payload["warning"]
    assert "QPS" in payload["warning"]
