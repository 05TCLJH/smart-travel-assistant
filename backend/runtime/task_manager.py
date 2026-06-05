"""Deploy-safe task manager backed by shared runtime storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.runtime.state_store import runtime_state_store


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@dataclass
class TaskSnapshot:
    task_id: str
    status: str
    progress_messages: list[Any]
    result: Any
    error: str | None
    version: int
    attempts: int
    created_at: float
    updated_at: float
    completed_at: float | None


class TaskCancellationHandle:
    """Cancellation view that works across workers by reading shared storage."""

    def __init__(self, task_id: str) -> None:
        self._task_id = task_id

    def is_set(self) -> bool:
        return runtime_state_store.is_task_cancel_requested(self._task_id)


class TripTaskManager:
    """Coordinate queue-backed task execution, polling SSE, and restart recovery."""

    def __init__(self) -> None:
        runtime_state_store.initialize()

    def recover_incomplete_tasks(self) -> int:
        return runtime_state_store.reconcile_incomplete_tasks()

    def create(self, task_id: str, *, owner_id: str) -> TaskSnapshot:
        task = runtime_state_store.create_task(task_id, owner_id)
        return self._snapshot(task)

    def enqueue(
        self,
        task_id: str,
        *,
        owner_id: str,
        request_payload: dict[str, Any],
        runtime_keys: dict[str, str],
    ) -> TaskSnapshot:
        task = runtime_state_store.enqueue_task(task_id, owner_id, request_payload, runtime_keys)
        return self._snapshot(task)

    def get_snapshot(self, task_id: str, *, owner_id: str | None = None) -> TaskSnapshot | None:
        task = runtime_state_store.get_task(task_id, owner_id=owner_id)
        return self._snapshot(task) if task else None

    def append_progress(self, task_id: str, event: Any) -> TaskSnapshot | None:
        task = runtime_state_store.append_task_progress(task_id, event)
        return self._snapshot(task) if task else None

    def claim_next(self, runner_id: str, lease_seconds: float) -> dict[str, Any] | None:
        return runtime_state_store.claim_next_task(runner_id, lease_seconds)

    def heartbeat(self, task_id: str, runner_id: str, lease_seconds: float) -> bool:
        return runtime_state_store.heartbeat_task(task_id, runner_id, lease_seconds)

    def get_execution_payload(self, task_id: str) -> dict[str, Any] | None:
        return runtime_state_store.get_task_execution_payload(task_id)

    def complete(self, task_id: str, result: Any) -> TaskSnapshot | None:
        task = runtime_state_store.complete_task(task_id, result)
        return self._snapshot(task) if task else None

    def fail(self, task_id: str, error: str) -> TaskSnapshot | None:
        task = runtime_state_store.fail_task(task_id, error)
        return self._snapshot(task) if task else None

    def cancel(self, task_id: str, *, event: Any | None = None) -> TaskSnapshot | None:
        task = runtime_state_store.cancel_task(task_id, event=event)
        return self._snapshot(task) if task else None

    def is_cancelled(self, task_id: str) -> bool:
        return runtime_state_store.is_task_cancel_requested(task_id)

    def get_cancel_event(self, task_id: str) -> TaskCancellationHandle | None:
        task = runtime_state_store.get_task(task_id)
        if task is None:
            return None
        return TaskCancellationHandle(task_id)

    def wait_for_update(self, task_id: str, last_version: int, timeout: float = 15.0) -> TaskSnapshot | None:
        task = runtime_state_store.wait_for_task_update(task_id, last_version, timeout)
        return self._snapshot(task) if task else None

    @staticmethod
    def _snapshot(task: dict[str, Any]) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=task["task_id"],
            status=task["status"],
            progress_messages=list(task["progress_messages"]),
            result=task["result"],
            error=task["error"],
            version=task["version"],
            attempts=int(task.get("attempts") or 0),
            created_at=task["created_at"],
            updated_at=task["updated_at"],
            completed_at=task["completed_at"],
        )
