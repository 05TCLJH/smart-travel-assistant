from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.services.report_service import ReportService


def _sample_trip_result() -> dict:
    return {
        "trip_request": {
            "destination": "上海",
            "days": 2,
            "start_date": "2026-06-04",
            "budget": 2000,
        },
        "plan": {
            "summary": "经典城市漫游",
            "itinerary": [],
        },
        "weather": {},
        "persona": {
            "name": "旅行者",
            "travel_style": "经典热门",
            "stamina": "适中",
            "budget_style": "舒适",
            "transport_preference": "打车/网约车优先",
            "likes": ["地标"],
        },
        "transport_plan": {},
        "food_recommendations": [],
        "lodging_recommendations": [],
        "tips": {"tips": []},
    }


def test_report_service_generates_pdf_in_memory() -> None:
    report = ReportService().generate(_sample_trip_result())

    assert report.filename.startswith("travel_report_")
    assert report.filename.endswith(".pdf")
    assert report.content.startswith(b"%PDF")
    assert len(report.content) > 100
    assert b"NotoSansSC" in report.content or b"STSong-Light" in report.content


def test_report_export_endpoint_returns_pdf_attachment() -> None:
    client = TestClient(create_app())

    response = client.post("/api/report/export", json={"trip_result": _sample_trip_result()})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "attachment;" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")
