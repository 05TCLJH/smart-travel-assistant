from __future__ import annotations

from backend.core.public_views import public_persona_profile, sanitize_trip_result


def test_public_persona_profile_strips_internal_fields() -> None:
    payload = public_persona_profile(
        {
            "name": "旅行者",
            "travel_style": "经典热门",
            "stamina": "适中",
            "budget_style": "舒适",
            "transport_preference": "打车/网约车优先",
            "likes": ["博物馆"],
        }
    )

    assert payload == {
        "name": "旅行者",
        "travel_style": "经典热门",
        "stamina": "适中",
        "budget_style": "舒适",
    }


def test_sanitize_trip_result_keeps_public_persona_only() -> None:
    trip_result = sanitize_trip_result(
        {
            "trip_request": {"destination": "西安"},
            "persona": {
                "name": "旅行者",
                "travel_style": "文化深度游",
                "stamina": "适中",
                "budget_style": "舒适",
                "transport_preference": "打车/网约车优先",
                "must_have": ["内容扎实"],
            },
        }
    )

    assert trip_result["persona"] == {
        "name": "旅行者",
        "travel_style": "文化深度游",
        "stamina": "适中",
        "budget_style": "舒适",
    }
