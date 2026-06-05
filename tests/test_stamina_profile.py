"""体力三档画像与单日装箱下限。"""

from __future__ import annotations

import unittest

from backend.planning.activity_load import (
    LOAD_LIGHT,
    LOAD_STANDARD,
    distribute_candidates_by_load,
    enrich_poi_with_activity_load,
)
from backend.planning.day_capacity import resolve_day_capacity
from backend.planning.stamina_profile import normalize_stamina, resolve_stamina_profile
from backend.services.persona_service import PersonaService
from backend.tools.routing_policy import merge_routing_policy


def _poi(name: str, type_text: str = "风景名胜") -> dict:
    return enrich_poi_with_activity_load({"name": name, "type": type_text})


class StaminaProfileTests(unittest.TestCase):
    def test_normalize_legacy_five_levels(self) -> None:
        self.assertEqual(normalize_stamina("弱"), "轻松")
        self.assertEqual(normalize_stamina("中等"), "适中")
        self.assertEqual(normalize_stamina("强"), "充沛")
        self.assertEqual(normalize_stamina(3), "充沛")
        self.assertEqual(normalize_stamina(1), "轻松")

    def test_moderate_capacity_floor(self) -> None:
        cap = resolve_day_capacity({"stamina": "适中"})
        self.assertGreaterEqual(cap.daily_load_budget, 95)
        self.assertGreaterEqual(cap.max_pois_cap, 3)
        self.assertEqual(cap.min_pois_per_day, 3)

    def test_intent_cannot_cap_below_profile_min(self) -> None:
        persona = {"stamina": "适中"}
        merged = merge_routing_policy({"max_pois_per_day": 1}, persona, {"days": 3, "budget": 3000})
        self.assertGreaterEqual(merged["max_pois_per_day"], 3)

    def test_distribute_backfill_moderate_city_day(self) -> None:
        pois = [
            _poi("昙华林历史文化街区", "历史文化街区"),
            _poi("江汉路步行街", "步行街"),
            _poi("汉口江滩", "公园广场"),
            _poi("黎黄陂路街头", "步行街"),
            _poi("武汉科技馆", "科技馆"),
            _poi("吉庆街夜市", "夜市"),
        ]
        profile = resolve_stamina_profile({"stamina": "适中"})
        cap = resolve_day_capacity({"stamina": "适中"})
        buckets = distribute_candidates_by_load(
            pois,
            1,
            cap.daily_load_budget,
            cap.max_pois_cap,
            min_pois_per_day=profile.min_pois_per_day,
            min_day_load_ratio=profile.min_day_load_ratio,
        )
        day = buckets[0]
        self.assertGreaterEqual(len(day), profile.min_pois_per_day)
        used = sum(int(p.get("activity_load", LOAD_STANDARD) or LOAD_STANDARD) for p in day)
        self.assertGreaterEqual(used, int(cap.daily_load_budget * profile.min_day_load_ratio * 0.9))

    def test_persona_service_recomputes_stale_budget(self) -> None:
        raw = {**PersonaService().load(), "stamina": "中等", "daily_activity_load_budget": 40, "max_pois_per_day": 1}
        normalized = PersonaService()._normalize(raw)
        self.assertEqual(normalized["stamina"], "适中")
        self.assertGreaterEqual(normalized["max_pois_per_day"], 3)
        self.assertGreaterEqual(normalized["daily_activity_load_budget"], 95)


if __name__ == "__main__":
    unittest.main()
