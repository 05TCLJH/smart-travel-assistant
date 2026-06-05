from __future__ import annotations

from backend.core.runtime_context import runtime_keys_scope
from backend.tools.amap_tools import TravelResearchTools


def test_runtime_key_can_enable_amap_weather_when_platform_switch_is_off(monkeypatch):
    monkeypatch.setenv("AMAP_MCP_ENABLED", "false")
    monkeypatch.delenv("AMAP_MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("AMAP_API_KEY", raising=False)
    monkeypatch.delenv("AMAP_MCP_API_KEY", raising=False)
    monkeypatch.delenv("AMAP_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("AMAP_WEB_SERVICE_KEY", raising=False)

    tools = TravelResearchTools()

    assert tools.mcp_enabled is False

    with runtime_keys_scope(amap_api_key="0123456789abcdef0123456789abcdef"):
        assert tools.mcp_enabled is True
        assert tools.amap.enabled is True

