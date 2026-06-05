"""运行时上下文与图工厂。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from backend.exceptions import TripGenerationCancelled
from backend.graphs.main_graph import build_trip_graph
from backend.mcp.travel_context_store import travel_context_store
from backend.runtime.checkpointer import get_checkpointer
from backend.runtime.model_registry import get_chat_model
from backend.tools.amap_tools import TravelResearchTools
from backend.tools.local_service_tools import LocalServiceTools


@dataclass
class TripGraphRuntime:
    persona_service: object
    research_tools: TravelResearchTools
    owner_id: str
    local_service_tools: LocalServiceTools | None = None
    progress_callback: Callable[..., Any] | None = None
    cancel_event: threading.Event | None = None
    max_revisions: int = 2

    def __post_init__(self) -> None:
        self.checkpointer = get_checkpointer()
        self.chat_model = get_chat_model(temperature=0.1)
        if self.local_service_tools is None:
            self.local_service_tools = LocalServiceTools(self.research_tools)

    def check_cancelled(self) -> None:
        if self.cancel_event and self.cancel_event.is_set():
            raise TripGenerationCancelled()

    def emit_progress(
        self,
        message: str,
        stage: str | None = None,
        *,
        step_id: str | None = None,
        status: str = "running",
    ) -> None:
        from backend.runtime.progress_catalog import build_progress_event

        self.emit_event(build_progress_event(message, stage=stage, step_id=step_id, status=status))

    def emit_step(self, step_id: str, status: str = "running", detail: str | None = None) -> None:
        from backend.runtime.progress_catalog import build_progress_event, get_step

        meta = get_step(step_id)
        message = str(detail or "").strip() or (meta.default_message if meta else step_id)
        stage = meta.stage if meta else None
        self.emit_event(build_progress_event(message, stage=stage, step_id=step_id, status=status))

    def emit_event(self, event: dict) -> None:
        self.check_cancelled()
        if not self.progress_callback:
            return
        try:
            self.progress_callback(event)
        except TypeError:
            self.progress_callback(str(event.get("message", "")), event.get("stage"))

    def start_context_session(self, session_id: str, seed: dict | None = None) -> None:
        travel_context_store.start_session(self.owner_id, session_id, seed or {})

    def publish_context(self, session_id: str, **sections) -> None:
        travel_context_store.publish(self.owner_id, session_id, **sections)

    def append_context_progress(self, session_id: str, message: str) -> None:
        travel_context_store.append_progress(self.owner_id, session_id, message)


def create_trip_graph(runtime: TripGraphRuntime):
    return build_trip_graph(runtime)
