from __future__ import annotations

from backend.tools.amap_tools import TravelResearchTools


def test_destination_scope_cache_reuses_single_geocode_call(monkeypatch):
    monkeypatch.setenv("AMAP_MCP_ENABLED", "true")
    monkeypatch.setenv("AMAP_API_KEY", "0123456789abcdef0123456789abcdef")

    tools = TravelResearchTools()
    calls: list[str] = []

    def fake_geocode(query: str) -> dict[str, object]:
        calls.append(query)
        return {
            "geocodes": [
                {
                    "location": "120.153576,30.287459",
                    "adcode": "330100",
                    "city": "杭州",
                }
            ]
        }

    monkeypatch.setattr(tools.amap, "geocode", fake_geocode)

    first = tools.get_destination_scope("杭州")
    second = tools.get_destination_scope("杭州")

    assert calls == ["杭州"]
    assert first == second

    first["city_ref"] = "mutated"
    third = tools.get_destination_scope("杭州")
    assert third["city_ref"] != "mutated"


def test_geocode_poi_queries_cache_reuses_same_place(monkeypatch):
    monkeypatch.setenv("AMAP_MCP_ENABLED", "true")
    monkeypatch.setenv("AMAP_API_KEY", "0123456789abcdef0123456789abcdef")

    tools = TravelResearchTools()
    calls: list[str] = []

    def fake_resolve(query: str) -> dict[str, object]:
        calls.append(query)
        return {
            "geocodes": [
                {
                    "location": f"120.0{len(calls)},30.0{len(calls)}",
                }
            ]
        }

    monkeypatch.setattr(tools, "resolve_geocode_payload", fake_resolve)

    first = tools._geocode_poi_queries("西湖", "北山路", "杭州", "浙江")
    second = tools._geocode_poi_queries("西湖", "北山路", "杭州", "浙江")

    assert len(first) == len(second) == 3
    assert first == second
    assert len(calls) == 3


def test_homonym_search_candidates_cache_reuses_text_search(monkeypatch):
    monkeypatch.setenv("AMAP_MCP_ENABLED", "true")
    monkeypatch.setenv("AMAP_API_KEY", "0123456789abcdef0123456789abcdef")

    tools = TravelResearchTools()
    calls: list[tuple[str, str]] = []

    def fake_text_search(
        query: str,
        *,
        city: str = "",
        extensions: str = "all",
        offset: int = 15,
    ) -> dict[str, object]:
        del extensions, offset
        calls.append((query, city))
        return {
            "pois": [
                {"name": "西湖景区", "location": "120.1,30.2"},
                {"name": "西湖", "location": "120.2,30.3"},
            ]
        }

    monkeypatch.setattr(tools.amap, "text_search", fake_text_search)

    first = tools._collect_homonym_search_candidates("西湖", "杭州", "")
    second = tools._collect_homonym_search_candidates("西湖", "杭州", "")

    assert first == second
    assert len(calls) == 1


def test_resolve_poi_coordinate_reuses_poi_id_cache(monkeypatch):
    monkeypatch.setenv("AMAP_MCP_ENABLED", "true")
    monkeypatch.setenv("AMAP_API_KEY", "0123456789abcdef0123456789abcdef")

    tools = TravelResearchTools()
    tools.osm_geocode_enabled = False
    geocode_calls: list[str] = []
    inspect_calls: list[str] = []

    def fake_geocode(query: str) -> dict[str, object]:
        geocode_calls.append(query)
        return {
            "geocodes": [
                {
                    "location": "120.111111,30.222222",
                }
            ]
        }

    def fake_inspect(location: str) -> dict[str, str]:
        inspect_calls.append(location)
        return {
            "formatted_address": "杭州西湖",
            "nearest_poi": "西湖",
            "nearest_type": "景区",
            "nearest_distance": "10",
        }

    monkeypatch.setattr(tools, "resolve_geocode_payload", lambda query: fake_geocode(query))
    monkeypatch.setattr(tools, "_inspect_regeocode", fake_inspect)

    row_a = {
        "id": "poi-123",
        "name": "西湖",
        "address": "北山路1号",
        "cityname": "杭州",
        "location": "120.100000,30.100000",
    }
    row_b = {
        "id": "poi-123",
        "name": "西湖",
        "address": "北山路1号",
        "cityname": "杭州",
        "location": "120.200000,30.200000",
    }

    first = tools._resolve_poi_coordinate(row_a, None, "杭州")
    second = tools._resolve_poi_coordinate(row_b, None, "杭州")

    assert first == second
    assert len(geocode_calls) == 3
    assert len(inspect_calls) >= 1
