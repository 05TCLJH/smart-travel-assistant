"""冒烟测试：POI 坐标解析（离线 + 可选实时高德）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.tools.amap_tools import TravelResearchTools


def run_offline_cases() -> bool:
    tools = TravelResearchTools()
    tools.mcp_enabled = False
    tools.osm_geocode_enabled = False
    tools.amap = type("DisabledAmap", (), {"enabled": False})()  # type: ignore[assignment]
    ok = True

    tower = {
        "name": "\u89c2\u666f\u9601",
        "address": "\u4e1c\u6e56\u533a\u6ee8\u6c5f\u8def1\u53f7",
        "location": "115.881691,28.681136",
        "entr_location": "115.880500,28.681000",
        "cityname": "\u5357\u660c\u5e02",
    }
    resolved = tools._resolve_poi_coordinate(tower, None, "\u5357\u660c")
    print(f"riverside tower (offline, entr): {resolved}")
    if resolved != "115.880500,28.681000":
        print("  FAIL: should prefer entrance coordinate")
        ok = False

    street = {
        "name": "\u4e07\u5bff\u5bab\u5386\u53f2\u6587\u5316\u8857\u533a",
        "address": "\u897f\u6e56\u533a\u4e2d\u5c71\u8def",
        "location": "115.887801,28.676809",
        "cityname": "\u5357\u660c\u5e02",
    }
    resolved_street = tools._resolve_poi_coordinate(street, None, "\u5357\u660c")
    print(f"inland street (offline): {resolved_street}")
    pair = tools.parse_lnglat(resolved_street or "")
    if not pair or abs(pair[0] - 115.887) > 0.01:
        print("  FAIL: inland POI should not be shifted far away")
        ok = False

    url = tools.build_static_map_preview(
        {"polyline": [], "status": "approximate"},
        [{"name": tower["name"], "location": resolved, "city": "\u5357\u660c\u5e02"}],
    )
    print(f"static map has labels=: {'labels=' in url}")
    if "labels=" in url:
        ok = False
    return ok


def main() -> None:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_poi_coordinate*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    ok = result.wasSuccessful() and run_offline_cases()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
