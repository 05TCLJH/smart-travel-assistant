"""Shared travel context storage built on the runtime SQLite store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.runtime.state_store import runtime_state_store


@dataclass
class TravelContextStore:
    def start_session(self, owner_id: str, session_id: str, seed: dict[str, Any] | None = None) -> None:
        runtime_state_store.start_context_session(owner_id, session_id, seed)

    def publish(self, owner_id: str, session_id: str, **sections: Any) -> None:
        runtime_state_store.publish_context(owner_id, session_id, **sections)

    def append_progress(self, owner_id: str, session_id: str, message: str) -> None:
        runtime_state_store.append_context_progress(owner_id, session_id, message)

    def list_sessions(self, owner_id: str) -> list[dict[str, Any]]:
        return runtime_state_store.list_context_sessions(owner_id)

    def snapshot(self, owner_id: str, session_id: str) -> dict[str, Any]:
        return runtime_state_store.get_context_session(owner_id, session_id)

    def read_resource(self, owner_id: str, uri: str) -> dict[str, Any]:
        return runtime_state_store.read_context_resource(owner_id, uri)


travel_context_store = TravelContextStore()
