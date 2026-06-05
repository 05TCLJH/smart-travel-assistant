"""探测高德 POI 字段以辅助多城市坐标解析。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.mcp.amap_client import AmapMcpClient
from backend.tools.amap_tools import TravelResearchTools


CASES = [
    ("南昌", "滕王阁"),
    ("南昌", "万寿宫历史文化街区"),
    ("上海", "外滩"),
    ("北京", "故宫博物院"),
    ("武汉", "黄鹤楼"),
    ("重庆", "洪崖洞"),
]


def _first_poi(search: dict) -> dict:
    pois = search.get("pois") or []
    if not pois:
        return {}
    for row in pois:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", ""))
        if str(row.get("parent", "") or row.get("parentid", "")).strip():
            continue
        return row
    return pois[0] if isinstance(pois[0], dict) else {}


def _regeo_summary(client: AmapMcpClient, loc: str) -> dict:
    if not loc:
        return {}
    try:
        payload = client.regeocode(loc)
    except Exception as exc:
        return {"error": str(exc)}
    regeocode = payload.get("regeocode") or payload
    if not isinstance(regeocode, dict):
        return {"raw_keys": list(payload.keys()) if isinstance(payload, dict) else []}
    addr = regeocode.get("formatted_address", "")
    comp = regeocode.get("addressComponent") or {}
    pois = regeocode.get("pois") or []
    nearest = pois[0] if pois and isinstance(pois[0], dict) else {}
    return {
        "formatted_address": addr,
        "township": comp.get("township", ""),
        "street": comp.get("streetNumber", comp.get("street", "")),
        "nearest_poi": nearest.get("name", ""),
        "nearest_type": nearest.get("type", ""),
        "nearest_direction": nearest.get("direction", ""),
        "nearest_distance": nearest.get("distance", ""),
    }


def main() -> None:
    client = AmapMcpClient()
    tools = TravelResearchTools()
    if not client.enabled:
        print("Amap MCP not configured")
        sys.exit(1)

    for city, keyword in CASES:
        print("\n" + "=" * 60)
        print(f"{city} / {keyword}")
        try:
            search = client.text_search(f"{city}{keyword}", city=city, extensions="all")
        except Exception as exc:
            print(f"  search failed: {exc}")
            continue
        row = _first_poi(search)
        if not row:
            print("  no poi")
            continue
        poi_id = str(row.get("id", "")).strip()
        detail = client.search_detail(poi_id) if poi_id else {}
        detail_rec = tools._unwrap_poi_record(detail)
        locs = {
            "search_location": str(row.get("location", "")),
            "entr_location": str(row.get("entr_location") or detail_rec.get("entr_location", "")),
            "exit_location": str(row.get("exit_location") or detail_rec.get("exit_location", "")),
        }
        resolved = tools._resolve_poi_coordinate(row, detail_rec, city)
        print(f"  name: {row.get('name')}")
        print(f"  address: {row.get('address')}")
        for k, v in locs.items():
            print(f"  {k}: {v}")
            if v:
                summary = _regeo_summary(client, v)
                print(f"    regeo: {json.dumps(summary, ensure_ascii=False)}")
        print(f"  RESOLVED: {resolved}")
        if resolved:
            print(f"  resolved regeo: {json.dumps(_regeo_summary(client, resolved), ensure_ascii=False)}")


if __name__ == "__main__":
    main()
