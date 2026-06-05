from __future__ import annotations

import os
import importlib
from pathlib import Path
import socket
import ssl
import tempfile
import time
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from urllib.error import URLError

from backend.core.runtime_context import runtime_keys_scope
from backend.core.runtime_owner import RUNTIME_OWNER_COOKIE
from backend.core import paths as core_paths
from backend.main import create_app
from backend.runtime.state_store import RuntimeStateStore, runtime_state_store
from backend.routers.trip import _fetch_static_map_content, _safe_static_map_failure


@pytest.fixture()
def isolated_runtime_store(tmp_path: Path) -> Iterator[Path]:
    original_path = runtime_state_store._db_path
    original_initialized = runtime_state_store._initialized
    runtime_state_store._db_path = tmp_path / "runtime_state.sqlite3"
    runtime_state_store._initialized = False
    runtime_state_store.initialize()
    try:
        yield runtime_state_store._db_path
    finally:
        runtime_state_store._initialized = False
        runtime_state_store._db_path = original_path
        runtime_state_store._initialized = original_initialized


def _sample_trip_request() -> dict:
    return {
        "destination": "Hangzhou",
        "start_date": "2026-06-10",
        "days": 2,
        "budget": 1800,
        "persona": {},
    }


def _wait_for_status(client: TestClient, task_id: str, expected: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/trip/result/{task_id}")
        if response.status_code == 200 and response.json().get("status") == expected:
            return response.json()
        time.sleep(0.1)
    raise AssertionError(f"task {task_id} did not reach status {expected}")


def test_runtime_store_reconciles_running_tasks(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path / "runtime_state.sqlite3")
    store.initialize()
    store.enqueue_task("task-a", "owner-a", {"trip_request": {"destination": "A"}, "persona": {}}, {})
    claimed = store.claim_next_task("runner-a", lease_seconds=30)
    assert claimed is not None

    recovered = store.reconcile_incomplete_tasks()
    snapshot = store.get_task("task-a", "owner-a")

    assert recovered == 1
    assert snapshot is not None
    assert snapshot["status"] == "queued"
    assert snapshot["progress_messages"][-1]["step_id"] == "system.restart"


def test_status_sets_runtime_owner_cookie(isolated_runtime_store: Path) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/system/status")

    assert response.status_code == 200
    assert RUNTIME_OWNER_COOKIE in response.cookies
    assert response.json()["success"] is True


def test_runtime_owner_header_is_not_trusted_by_default(isolated_runtime_store: Path) -> None:
    with TestClient(create_app()) as client_a:
        client_a.get("/api/system/status")
        owner_a = client_a.cookies.get(RUNTIME_OWNER_COOKIE)
        assert owner_a
        runtime_state_store.enqueue_task("task-header-check", owner_a, {"trip_request": {"destination": "A"}, "persona": {}}, {})

    with TestClient(create_app()) as client_b:
        response = client_b.get("/api/trip/result/task-header-check", headers={"x-travel-owner": owner_a})

    assert response.status_code == 404


def test_status_can_emit_cross_site_runtime_owner_cookie(isolated_runtime_store: Path) -> None:
    with patch.dict(os.environ, {"RUNTIME_OWNER_COOKIE_SAMESITE": "none"}, clear=False):
        with TestClient(create_app()) as client:
            response = client.get("/api/system/status")

    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "samesite=none" in set_cookie
    assert "secure" in set_cookie


def test_trip_result_is_isolated_by_runtime_owner(monkeypatch: pytest.MonkeyPatch, isolated_runtime_store: Path) -> None:
    class StubTravelService:
        def generate(self, *args, **kwargs):
            return {"plan": {"summary": "stubbed"}, "tips": {"tips": []}}

    monkeypatch.setattr("backend.runtime.task_runner.build_travel_service", lambda: StubTravelService())

    with TestClient(create_app()) as client_a:
        create_response = client_a.post("/api/trip/plan", json=_sample_trip_request())
        task_id = create_response.json()["task_id"]
        result_a = _wait_for_status(client_a, task_id, "completed")

        assert result_a["data"]["plan"]["summary"] == "stubbed"

        with TestClient(create_app()) as client_b:
            result_b = client_b.get(f"/api/trip/result/{task_id}")
            assert result_b.status_code == 404


def test_static_map_ticket_is_not_shareable_across_runtime_owners(isolated_runtime_store: Path) -> None:
    with TestClient(create_app()) as client_a:
        client_a.get("/api/system/status")
        owner_a = client_a.cookies.get(RUNTIME_OWNER_COOKIE)
        assert owner_a

        with runtime_keys_scope(owner_id=owner_a, amap_api_key="0123456789abcdef0123456789abcdef"):
            ticket = runtime_state_store.create_static_map_ticket(
                owner_a,
                "0123456789abcdef0123456789abcdef",
                {"markers": "mid,0xE45B5B,1:120.1,30.2", "size": "760*360"},
            )

        with TestClient(create_app()) as client_b:
            response = client_b.get(f"/api/trip/static-map?ticket={ticket}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "belongs to another runtime owner" in response.text


def test_trip_sync_route_is_disabled_by_default(isolated_runtime_store: Path) -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/trip/plan/sync", json=_sample_trip_request())

    assert response.status_code == 404
    assert response.json()["detail"] == "Synchronous trip planning is disabled for deployment safety."


def test_progress_stream_can_resume_after_known_message_count(isolated_runtime_store: Path) -> None:
    with TestClient(create_app()) as client:
        client.get("/api/system/status")
        owner_id = client.cookies.get(RUNTIME_OWNER_COOKIE)
        assert owner_id

        runtime_state_store.enqueue_task("task-resume-sse", owner_id, {"trip_request": {"destination": "A"}, "persona": {}}, {})
        runtime_state_store.append_task_progress("task-resume-sse", {"message": "first", "stage": "planning"})
        runtime_state_store.append_task_progress("task-resume-sse", {"message": "second", "stage": "planning"})
        runtime_state_store.complete_task("task-resume-sse", {"ok": True})

        response = client.get("/api/trip/progress/task-resume-sse?after=2")

    assert response.status_code == 200
    assert '"message": "second"' in response.text
    assert '"message": "first"' not in response.text
    assert '"type": "complete"' in response.text


def test_static_map_errors_do_not_echo_runtime_key(isolated_runtime_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app()) as client:
        client.get("/api/system/status")
        owner_id = client.cookies.get(RUNTIME_OWNER_COOKIE)
        assert owner_id

        with runtime_keys_scope(owner_id=owner_id, amap_api_key="0123456789abcdef0123456789abcdef"):
            ticket = runtime_state_store.create_static_map_ticket(
                owner_id,
                "0123456789abcdef0123456789abcdef",
                {"markers": "mid,0xE45B5B,1:120.1,30.2", "size": "760*360"},
            )

        def _boom(*args, **kwargs):
            raise RuntimeError("https://restapi.amap.com/v3/staticmap?key=0123456789abcdef0123456789abcdef")

        monkeypatch.setattr("backend.routers.trip.urlopen", _boom)
        response = client.get(f"/api/trip/static-map?ticket={ticket}")

    assert response.status_code == 200
    assert "0123456789abcdef0123456789abcdef" not in response.text
    assert "Static map request failed unexpectedly." in response.text


def test_safe_static_map_failure_reports_timeout() -> None:
    message = _safe_static_map_failure(URLError(socket.timeout("timed out")))
    assert message == "Static map service timed out."


def test_safe_static_map_failure_reports_ssl_handshake() -> None:
    message = _safe_static_map_failure(URLError(ssl.SSLError("tlsv1 alert internal error")))
    assert message == "Static map SSL handshake failed."


def test_fetch_static_map_content_retries_retryable_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    class _FakeResponse:
        def __init__(self, content: bytes, content_type: str) -> None:
            self._content = content
            self.headers = {"Content-Type": content_type}

        def read(self) -> bytes:
            return self._content

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(request, timeout=0):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise URLError(socket.timeout("timed out"))
        return _FakeResponse(b"png-bytes", "image/png")

    monkeypatch.setattr("backend.routers.trip.urlopen", _fake_urlopen)
    monkeypatch.setattr("backend.routers.trip.time.sleep", lambda *_args, **_kwargs: None)

    content, content_type = _fetch_static_map_content("https://example.com/static-map")

    assert content == b"png-bytes"
    assert content_type == "image/png"
    assert len(attempts) == 2


def test_travel_context_mcp_is_disabled_by_default(isolated_runtime_store: Path) -> None:
    with TestClient(create_app()) as client:
        client.get("/api/system/status")

        with patch.dict(os.environ, {"TRAVEL_CONTEXT_MCP_ENABLED": "0"}, clear=False):
            response = client.post(
                "/mcp/travel-context",
                headers={"x-travel-context-token": "test-token"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["message"] == "Travel Context MCP is disabled"


def test_root_injects_public_api_base_url(isolated_runtime_store: Path) -> None:
    with patch.dict(os.environ, {"PUBLIC_API_BASE_URL": "https://api.example.com"}, clear=False):
        with TestClient(create_app()) as client:
            response = client.get("/")

    assert response.status_code == 200
    assert "https://api.example.com" in response.text


def test_space_runtime_root_defaults_to_tmp() -> None:
    with patch.dict(os.environ, {"SPACE_ID": "owner/demo-space"}, clear=False):
        reloaded = importlib.reload(core_paths)
        assert reloaded.RUNTIME_DATA_ROOT == Path(tempfile.gettempdir()) / "smart-travel-assistant"
    importlib.reload(core_paths)
