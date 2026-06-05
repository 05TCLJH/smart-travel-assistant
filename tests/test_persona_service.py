"""Persona service contract tests."""

from __future__ import annotations

import unittest

from backend.services.persona_service import PersonaService


class PersonaServiceTests(unittest.TestCase):
    def test_enrich_derives_internal_preferences_on_server(self) -> None:
        service = PersonaService()
        persona = service.enrich({"travel_style": "文化深度游"}, {"destination": "西安", "days": 3, "budget": 4000})

        self.assertEqual(persona["likes"], ["博物馆", "历史文化"])
        self.assertEqual(persona["must_have"], ["内容扎实", "讲解友好"])
        self.assertIn("search_strategy", persona)
        self.assertIn("transport_preference", persona)

    def test_save_only_persists_public_profile_fields(self) -> None:
        service = PersonaService()
        saved = service.save(
            {
                "name": "小旅",
                "travel_style": "休闲度假",
                "stamina": "适中",
                "budget_style": "舒适",
                "transport_preference": "打车/网约车优先",
                "likes": ["博物馆"],
            }
        )

        self.assertEqual(set(saved.keys()), {"name", "travel_style", "stamina", "budget_style"})
        self.assertEqual(saved["name"], "小旅")
        self.assertNotIn("transport_preference", saved)
        self.assertNotIn("likes", saved)
        self.assertNotIn("must_have", saved)
        self.assertNotIn("daily_activity_load_budget", saved)

    def test_load_returns_clean_default_public_profile(self) -> None:
        service = PersonaService()
        loaded = service.load()

        self.assertEqual(set(loaded.keys()), {"name", "travel_style", "stamina", "budget_style"})
        self.assertEqual(loaded["name"], "旅行者")
        self.assertEqual(loaded["travel_style"], "经典热门")
        self.assertEqual(loaded["stamina"], "适中")
        self.assertEqual(loaded["budget_style"], "舒适")

    def test_reset_matches_load(self) -> None:
        service = PersonaService()
        self.assertEqual(service.reset(), service.load())


if __name__ == "__main__":
    unittest.main()
