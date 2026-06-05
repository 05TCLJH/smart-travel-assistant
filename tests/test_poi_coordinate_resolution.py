"""离线测试：与城市无关的景点坐标解析。"""
from __future__ import annotations

import unittest

from backend.tools.amap_tools import TravelResearchTools, _PoiCoordinateCandidate


RISKY_NAME = "\u89c2\u666f\u9601"
RISKY_ADDRESS = "\u4e1c\u6e56\u533a\u6ee8\u6c5f\u8def1\u53f7"
RIVER_CENTROID = "115.881691,28.681136"
LAND_ADDRESS_POINT = "115.880500,28.681000"


class PoiCoordinateResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = TravelResearchTools()
        self.tools.mcp_enabled = False
        self.tools.osm_geocode_enabled = False

    def test_same_name_on_water_gets_penalty_not_bonus(self) -> None:
        inspections = {
            RIVER_CENTROID: {
                "formatted_address": "\u6c5f\u897f\u7701\u5357\u660c\u5e02\u8d63\u6c5f\u6c5f\u5fc3",
                "nearest_poi": RISKY_NAME,
                "nearest_type": "\u98ce\u666f\u540d\u80dc",
            },
            LAND_ADDRESS_POINT: {
                "formatted_address": "\u6c5f\u897f\u7701\u5357\u660c\u5e02\u4e1c\u6e56\u533a\u6ee8\u6c5f\u8def1\u53f7",
                "nearest_poi": RISKY_NAME,
                "nearest_type": "\u98ce\u666f\u540d\u80dc",
            },
        }
        river_score = self.tools._score_poi_coordinate_candidate(
            _PoiCoordinateCandidate(RIVER_CENTROID, "search"),
            RISKY_NAME,
            self.tools.parse_lnglat(LAND_ADDRESS_POINT),
            inspections,
        )
        land_score = self.tools._score_poi_coordinate_candidate(
            _PoiCoordinateCandidate(LAND_ADDRESS_POINT, "geocode_address"),
            RISKY_NAME,
            self.tools.parse_lnglat(LAND_ADDRESS_POINT),
            inspections,
        )
        self.assertGreater(land_score, river_score)

    def test_address_geocode_beats_river_centroid(self) -> None:
        candidates = [
            _PoiCoordinateCandidate(RIVER_CENTROID, "search"),
            _PoiCoordinateCandidate(LAND_ADDRESS_POINT, "geocode_address"),
        ]
        inspections = {
            RIVER_CENTROID: {
                "formatted_address": "\u6c5f\u897f\u7701\u5357\u660c\u5e02\u8d63\u6c5f\u6c5f\u5fc3",
                "nearest_poi": "\u8d63\u6c5f",
                "nearest_type": "\u6cb3\u6d41",
            },
            LAND_ADDRESS_POINT: {
                "formatted_address": "\u6c5f\u897f\u7701\u5357\u660c\u5e02\u4e1c\u6e56\u533a\u6ee8\u6c5f\u8def1\u53f7",
                "nearest_poi": RISKY_NAME,
                "nearest_type": "\u98ce\u666f\u540d\u80dc",
            },
        }
        original = self.tools._inspect_regeocode

        def fake_inspect(loc: str) -> dict:
            return inspections.get(loc, {})

        self.tools._inspect_regeocode = fake_inspect  # type: ignore[method-assign]
        try:
            picked = self.tools._select_best_poi_coordinate(RISKY_NAME, RISKY_ADDRESS, "\u5357\u660c\u5e02", candidates)
        finally:
            self.tools._inspect_regeocode = original  # type: ignore[method-assign]
        self.assertEqual(picked, LAND_ADDRESS_POINT)

    def test_entrance_beats_river_centroid(self) -> None:
        candidates = [
            _PoiCoordinateCandidate(LAND_ADDRESS_POINT, "entr"),
            _PoiCoordinateCandidate(RIVER_CENTROID, "search"),
            _PoiCoordinateCandidate(RIVER_CENTROID, "geocode_name"),
        ]
        inspections = {
            LAND_ADDRESS_POINT: {
                "formatted_address": "\u6c5f\u897f\u7701\u5357\u660c\u5e02\u4e1c\u6e56\u533a\u6ee8\u6c5f\u8def1\u53f7",
                "nearest_poi": RISKY_NAME,
                "nearest_type": "\u98ce\u666f\u540d\u80dc",
            },
            RIVER_CENTROID: {
                "formatted_address": "\u6c5f\u897f\u7701\u5357\u660c\u5e02\u8d63\u6c5f\u6c5f\u5fc3",
                "nearest_poi": "\u8d63\u6c5f",
                "nearest_type": "\u6cb3\u6d41",
            },
        }
        original = self.tools._inspect_regeocode

        def fake_inspect(loc: str) -> dict:
            return inspections.get(loc, {})

        self.tools._inspect_regeocode = fake_inspect  # type: ignore[method-assign]
        try:
            picked = self.tools._select_best_poi_coordinate(RISKY_NAME, RISKY_ADDRESS, "\u5357\u660c\u5e02", candidates)
        finally:
            self.tools._inspect_regeocode = original  # type: ignore[method-assign]
        self.assertEqual(picked, LAND_ADDRESS_POINT)

    def test_normalize_pois_resolves_risky_search_coordinate(self) -> None:
        row = {
            "name": RISKY_NAME,
            "address": RISKY_ADDRESS,
            "cityname": "\u5357\u660c\u5e02",
            "location": RIVER_CENTROID,
            "type": "\u98ce\u666f\u540d\u80dc",
            "biz_ext": {"rating": "4.8"},
        }
        original = self.tools._resolve_poi_coordinate

        def fake_resolve(row_rec: dict, detail: dict | None, destination: str = "") -> str:
            return LAND_ADDRESS_POINT

        self.tools._resolve_poi_coordinate = fake_resolve  # type: ignore[method-assign]
        try:
            pois = self.tools._normalize_pois([row], LAND_ADDRESS_POINT, "\u5357\u660c", {}, None)
        finally:
            self.tools._resolve_poi_coordinate = original  # type: ignore[method-assign]
        self.assertEqual(pois[0]["location"], LAND_ADDRESS_POINT)

    def test_inland_poi_not_shifted_by_city_rule(self) -> None:
        raw = "115.887801,28.676809"
        geocode = "115.887100,28.674621"
        candidates = [
            _PoiCoordinateCandidate(raw, "search"),
            _PoiCoordinateCandidate(geocode, "geocode_address"),
        ]
        picked = self.tools._select_best_poi_coordinate(
            "\u4e07\u5bff\u5bab\u5386\u53f2\u6587\u5316\u8857\u533a",
            "\u897f\u6e56\u533a\u4e2d\u5c71\u8def",
            "\u5357\u660c\u5e02",
            candidates,
        )
        pair = self.tools.parse_lnglat(picked)
        self.assertIsNotNone(pair)
        assert pair is not None
        self.assertLess(abs(pair[0] - 115.888), 0.006)

    def test_water_detection_for_riverside_landmark(self) -> None:
        self.assertTrue(
            self.tools._is_water_like_point(
                {"formatted_address": "\u5357\u660c\u5e02\u8d63\u6c5f\u6c5f\u5fc3", "nearest_poi": "\u8d63\u6c5f", "nearest_type": "\u6cb3\u6d41"},
                RISKY_NAME,
            )
        )
        self.assertFalse(
            self.tools._is_water_like_point(
                {"formatted_address": "\u5357\u660c\u5e02\u7ea2\u8c37\u6ee9\u8d63\u6c5f\u4e2d\u5927\u9053", "nearest_poi": "\u79cb\u6c34\u5e7f\u573a", "nearest_type": "\u5e7f\u573a"},
                "\u79cb\u6c34\u5e7f\u573a",
            )
        )

    def test_wgs84_to_gcj02_in_china(self) -> None:
        lng, lat = self.tools._wgs84_to_gcj02(115.872898, 28.676714)
        self.assertNotEqual(lng, 115.872898)
        self.assertNotEqual(lat, 28.676714)
        self.assertTrue(self.tools._in_china_bbox(lng, lat))

    def test_resolve_prefers_entrance_from_row(self) -> None:
        row = {
            "name": "\u9ec4\u9e64\u697c",
            "address": "\u6b66\u660c\u533a\u86c7\u5c71\u897f\u5c71\u5761\u72791\u53f7",
            "cityname": "\u6b66\u6c49\u5e02",
            "location": "114.290000,30.540000",
            "entr_location": "114.297047,30.547081",
        }
        resolved = self.tools._resolve_poi_coordinate(row, None, "\u6b66\u6c49")
        self.assertEqual(resolved, "114.297047,30.547081")


if __name__ == "__main__":
    unittest.main()
