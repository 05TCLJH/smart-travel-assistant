"""Background runner for queue-backed trip generation tasks."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from backend.core.runtime_context import runtime_keys_scope
from backend.core.settings import runtime_task_lease_seconds, runtime_task_poll_seconds
from backend.exceptions import TripGenerationCancelled
from backend.runtime.progress_catalog import build_progress_event
from backend.runtime.task_manager import TripTaskManager
from backend.services.factory import create_travel_service
from backend.services.travel_service import TravelService


TASK_CANCELLED = "Task cancelled"


def build_travel_service() -> TravelService:
    return create_travel_service()


class TripTaskRunner:
    """Claim queued tasks from shared storage and execute them in the background."""

    def __init__(self, *, runner_id: str | None = None) -> None:
        self._runner_id = runner_id or uuid.uuid4().hex
        self._manager = TripTaskManager()
        self._lease_seconds = runtime_task_lease_seconds()
        self._poll_seconds = runtime_task_poll_seconds()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name=f"trip-task-runner-{self._runner_id[:8]}", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            claimed = self._manager.claim_next(self._runner_id, self._lease_seconds)
            if not claimed:
                self._stop_event.wait(self._poll_seconds)
                continue
            try:
                self._execute_task(claimed)
            except Exception as exc:
                task_id = str(claimed.get("task_id", "")).strip()
                if task_id:
                    self._manager.fail(task_id, f"Task runner crashed unexpectedly: {exc}")

    def _execute_task(self, claimed: dict[str, Any]) -> None:
        task_id = str(claimed.get("task_id", "")).strip()
        owner_id = str(claimed.get("owner_id", "")).strip()
        request_payload = claimed.get("request_payload", {}) if isinstance(claimed.get("request_payload"), dict) else {}
        runtime_keys = claimed.get("runtime_keys", {}) if isinstance(claimed.get("runtime_keys"), dict) else {}
        trip_request = request_payload.get("trip_request", {}) if isinstance(request_payload.get("trip_request"), dict) else {}
        persona = request_payload.get("persona", {}) if isinstance(request_payload.get("persona"), dict) else {}

        if not task_id or not owner_id or not trip_request:
            if task_id:
                self._manager.fail(task_id, "Task payload is incomplete and cannot be resumed.")
            return

        service = build_travel_service()

        def report(event_or_message: str | dict[str, Any], stage: str | None = None, **kwargs: Any) -> None:
            if isinstance(event_or_message, dict):
                event_payload = event_or_message
            else:
                event_payload = build_progress_event(
                    str(event_or_message),
                    stage=stage,
                    step_id=kwargs.get("step_id"),
                    status=kwargs.get("status", "running"),
                )
            self._manager.append_progress(task_id, event_payload)

        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(task_id, heartbeat_stop),
            name=f"trip-task-heartbeat-{task_id[:8]}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            cancel_event = self._manager.get_cancel_event(task_id)
            if cancel_event is None or cancel_event.is_set():
                raise TripGenerationCancelled()
            with runtime_keys_scope(owner_id=owner_id, **runtime_keys):
                result = service.generate(
                    trip_request,
                    persona,
                    progress=report,
                    cancel_event=cancel_event,
                    runtime_keys=runtime_keys,
                    owner_id=owner_id,
                    session_id=task_id,
                )
            if cancel_event.is_set():
                raise TripGenerationCancelled()
            self._manager.append_progress(
                task_id,
                build_progress_event("Trip generation completed.", stage="done", step_id="system.complete", status="done"),
            )
            self._manager.complete(task_id, result)
        except TripGenerationCancelled:
            self._manager.cancel(
                task_id,
                event=build_progress_event(TASK_CANCELLED, stage="cancelled", step_id="system.cancelled", status="cancelled"),
            )
        except Exception as exc:
            self._manager.append_progress(
                task_id,
                build_progress_event(
                    f"Trip generation failed: {exc}",
                    stage="error",
                    step_id="system.error",
                    status="error",
                ),
            )
            self._manager.fail(task_id, str(exc))
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1.0)

    def _heartbeat_loop(self, task_id: str, stop_event: threading.Event) -> None:
        interval = max(5.0, self._lease_seconds / 3.0)
        while not stop_event.wait(interval):
            if not self._manager.heartbeat(task_id, self._runner_id, self._lease_seconds):
                return
