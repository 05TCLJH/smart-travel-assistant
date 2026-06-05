"""离线演示景点目录测试。"""

from __future__ import annotations

import unittest

from backend.knowledge.demo_catalog import (
    _load_demo_library,
    has_demo_coverage,
    load_demo_pois,
    resolve_demo_destination_key,
)
from backend.planning.poi_retrieval.fallback import build_fallback_map_payload, supplement_with_demo_pois


class DemoCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _load_demo_library.cache_clear()

    def test_resolve_via_catalog_alias(self) -> None:
        self.assertEqual(resolve_demo_destination_key("北京市"), "北京")
        self.assertEqual(resolve_demo_destination_key("南昌市"), "南昌")

    def test_load_nanchang_pois(self) -> None:
        meta, pois = load_demo_pois("南昌")
        self.assertIn("滕王阁", [p["name"] for p in pois])
        self.assertEqual(meta["resolved_name"], "江西省南昌市")
        self.assertTrue(all(p.get("popularity_score") for p in pois))

    def test_unknown_destination_empty_pois(self) -> None:
        self.assertFalse(has_demo_coverage("川西"))
        _, pois = load_demo_pois("川西")
        self.assertEqual(pois, [])

    def test_fallback_payload_flags(self) -> None:
        payload = build_fallback_map_payload("上海", reason="体验模式")
        self.assertTrue(payload["is_fallback"])
        self.assertTrue(payload["demo_coverage"])
        self.assertGreater(len(payload["pois"]), 5)

    def test_supplement_skips_without_demo(self) -> None:
        base = [{"name": "稻城亚丁", "location": "1,2"}]
        out = supplement_with_demo_pois("川西", {"travel_style": "经典热门", "trip_days": 3}, base)
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
