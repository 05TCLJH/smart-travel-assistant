"""基于 SQLite 的共享运行时状态存储。

该存储有意保持轻量且短生命周期：
- 任务队列状态与结果
- 旅行上下文快照
- 短期静态地图票据
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any

from backend.core.paths import RUNTIME_DIR
from backend.core.settings import runtime_state_db_path


def _now_ts() -> float:
    return time.time()


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return deepcopy(default)
    try:
        return json.loads(raw)
    except Exception:
        return deepcopy(default)


class RuntimeStateStore:
    def __init__(
        self,
        db_path: Path | None = None,
        *,
        task_retention_seconds: float = 1800.0,
        context_ttl_seconds: float = 6 * 3600.0,
        ticket_ttl_seconds: float = 1800.0,
    ) -> None:
        self._db_path = db_path or runtime_state_db_path() or (RUNTIME_DIR / "runtime_state.sqlite3")
        self._task_retention_seconds = task_retention_seconds
        self._context_ttl_seconds = context_ttl_seconds
        self._ticket_ttl_seconds = ticket_ttl_seconds
        self._init_lock = threading.RLock()
        self._initialized = False

    def initialize(self) -> None:
        with self._init_lock:
            if self._initialized:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trip_tasks (
                        task_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        progress_json TEXT NOT NULL,
                        request_json TEXT,
                        runtime_keys_json TEXT,
                        result_json TEXT,
                        error TEXT,
                        version INTEGER NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,
                        runner_id TEXT,
                        lease_expires_at REAL,
                        started_at REAL,
                        heartbeat_at REAL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        completed_at REAL,
                        expires_at REAL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_trip_tasks_owner_updated
                    ON trip_tasks(owner_id, updated_at DESC)
                    """
                )
                self._ensure_column(conn, "trip_tasks", "request_json", "TEXT")
                self._ensure_column(conn, "trip_tasks", "runtime_keys_json", "TEXT")
                self._ensure_column(conn, "trip_tasks", "attempts", "INTEGER NOT NULL DEFAULT 0")
                self._ensure_column(conn, "trip_tasks", "runner_id", "TEXT")
                self._ensure_column(conn, "trip_tasks", "lease_expires_at", "REAL")
                self._ensure_column(conn, "trip_tasks", "started_at", "REAL")
                self._ensure_column(conn, "trip_tasks", "heartbeat_at", "REAL")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS travel_context_sessions (
                        session_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        updated_at REAL NOT NULL,
                        expires_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_travel_context_owner_updated
                    ON travel_context_sessions(owner_id, updated_at DESC)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS static_map_tickets (
                        ticket_id TEXT PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        amap_api_key TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        expires_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_static_map_owner_exp
                    ON static_map_tickets(owner_id, expires_at)
                    """
                )
            self._initialized = True

    def reconcile_incomplete_tasks(self) -> int:
        self.initialize()
        now = _now_ts()
        recovered = 0
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, progress_json, version
                FROM trip_tasks
                WHERE status IN ('queued', 'running') AND completed_at IS NULL
                """
            ).fetchall()
            for row in rows:
                progress = _json_loads(row["progress_json"], [])
                progress.append(
                    {
                        "type": "progress",
                        "stage": "system",
                        "step_id": "system.restart",
                        "status": "running",
                        "message": "Service restarted, task returned to the shared queue.",
                    }
                )
                conn.execute(
                    """
                    UPDATE trip_tasks
                    SET status = ?, progress_json = ?, version = ?, runner_id = ?, lease_expires_at = ?,
                        started_at = ?, heartbeat_at = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (
                        "queued",
                        _json_dumps(progress),
                        int(row["version"]) + 1,
                        None,
                        None,
                        None,
                        None,
                        now,
                        row["task_id"],
                    ),
                )
                recovered += 1
        return recovered

    def create_task(self, task_id: str, owner_id: str) -> dict[str, Any] | None:
        return self.enqueue_task(task_id, owner_id, {"trip_request": {}, "persona": {}}, {})

    def enqueue_task(
        self,
        task_id: str,
        owner_id: str,
        request_payload: dict[str, Any],
        runtime_keys: dict[str, str],
    ) -> dict[str, Any] | None:
        self.initialize()
        self.prune_expired()
        now = _now_ts()
        progress = [
            {
                "type": "progress",
                "stage": "system",
                "step_id": "system.queued",
                "status": "running",
                "message": "Task accepted and queued for execution.",
            }
        ]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trip_tasks (
                    task_id, owner_id, status, progress_json, request_json, runtime_keys_json,
                    result_json, error, version, attempts, cancel_requested, runner_id,
                    lease_expires_at, started_at, heartbeat_at, created_at, updated_at,
                    completed_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    owner_id,
                    "queued",
                    _json_dumps(progress),
                    _json_dumps(request_payload),
                    _json_dumps(runtime_keys),
                    None,
                    None,
                    0,
                    0,
                    0,
                    None,
                    None,
                    None,
                    None,
                    now,
                    now,
                    None,
                    None,
                ),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str, owner_id: str | None = None) -> dict[str, Any] | None:
        self.initialize()
        self.prune_expired()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM trip_tasks WHERE task_id = ?", (task_id,)).fetchone()
        task = self._task_from_row(row)
        if not task:
            return None
        if owner_id is not None and task["owner_id"] != owner_id:
            return None
        return task

    def append_task_progress(self, task_id: str, event: Any) -> dict[str, Any] | None:
        self.initialize()
        now = _now_ts()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM trip_tasks WHERE task_id = ?", (task_id,)).fetchone()
            task = self._task_from_row(row)
            if not task:
                return None
            progress = list(task["progress_messages"])
            progress.append(deepcopy(event))
            conn.execute(
                """
                UPDATE trip_tasks
                SET progress_json = ?, version = ?, updated_at = ?, heartbeat_at = ?
                WHERE task_id = ?
                """,
                (_json_dumps(progress), task["version"] + 1, now, now, task_id),
            )
        return self.get_task(task_id)

    def claim_next_task(self, runner_id: str, lease_seconds: float) -> dict[str, Any] | None:
        self.initialize()
        self.prune_expired()
        now = _now_ts()
        lease_expires_at = now + max(lease_seconds, 30.0)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    """
                    SELECT *
                    FROM trip_tasks
                    WHERE status = 'queued' AND cancel_requested = 0
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                reclaimed = False
                if row is None:
                    row = conn.execute(
                        """
                        SELECT *
                        FROM trip_tasks
                        WHERE status = 'running'
                          AND cancel_requested = 0
                          AND (lease_expires_at IS NULL OR lease_expires_at < ?)
                        ORDER BY updated_at ASC
                        LIMIT 1
                        """,
                        (now,),
                    ).fetchone()
                    reclaimed = row is not None
                if row is None:
                    conn.execute("COMMIT")
                    return None

                task = self._task_from_row(row)
                progress = list(task["progress_messages"])
                progress.append(
                    {
                        "type": "progress",
                        "stage": "system",
                        "step_id": "system.resume" if reclaimed else "system.picked",
                        "status": "running",
                        "message": "Task lease expired and execution resumed on another worker."
                        if reclaimed
                        else "Worker picked up the queued task.",
                    }
                )
                cursor = conn.execute(
                    """
                    UPDATE trip_tasks
                    SET status = ?, progress_json = ?, version = ?, attempts = ?, error = ?, runner_id = ?,
                        lease_expires_at = ?, started_at = ?, heartbeat_at = ?, updated_at = ?
                    WHERE task_id = ? AND (
                        status = 'queued' OR
                        (status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at < ?))
                    )
                    """,
                    (
                        "running",
                        _json_dumps(progress),
                        task["version"] + 1,
                        task["attempts"] + 1,
                        None,
                        runner_id,
                        lease_expires_at,
                        task["started_at"] or now,
                        now,
                        now,
                        task["task_id"],
                        now,
                    ),
                )
                if cursor.rowcount != 1:
                    conn.execute("ROLLBACK")
                    return None
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        claimed = self.get_task(task["task_id"])
        if claimed is None:
            return None
        claimed["claimed_from_stale_lease"] = reclaimed
        return claimed

    def heartbeat_task(self, task_id: str, runner_id: str, lease_seconds: float) -> bool:
        self.initialize()
        now = _now_ts()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE trip_tasks
                SET lease_expires_at = ?, heartbeat_at = ?, updated_at = ?
                WHERE task_id = ? AND runner_id = ? AND status = 'running'
                """,
                (now + max(lease_seconds, 30.0), now, now, task_id, runner_id),
            )
        return cursor.rowcount == 1

    def get_task_execution_payload(self, task_id: str) -> dict[str, Any] | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        return {
            "task_id": task["task_id"],
            "owner_id": task["owner_id"],
            "request_payload": deepcopy(task["request_payload"]),
            "runtime_keys": deepcopy(task["runtime_keys"]),
            "attempts": int(task["attempts"]),
            "status": task["status"],
            "claimed_from_stale_lease": bool(task.get("claimed_from_stale_lease")),
        }

    def complete_task(self, task_id: str, result: Any) -> dict[str, Any] | None:
        return self._transition_task(task_id, status="completed", result=result, error=None)

    def fail_task(self, task_id: str, error: str) -> dict[str, Any] | None:
        return self._transition_task(task_id, status="failed", result=None, error=str(error))

    def cancel_task(self, task_id: str, *, event: Any | None = None) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM trip_tasks WHERE task_id = ?", (task_id,)).fetchone()
            task = self._task_from_row(row)
            if not task:
                return None
            progress = list(task["progress_messages"])
            if event is not None and event not in progress:
                progress.append(deepcopy(event))
            now = _now_ts()
            status = task["status"] if task["status"] not in {"queued", "running"} else "cancelled"
            completed_at = task["completed_at"] if status != "cancelled" else now
            expires_at = task["expires_at"] if status != "cancelled" else now + self._task_retention_seconds
            conn.execute(
                """
                UPDATE trip_tasks
                SET status = ?, progress_json = ?, result_json = ?, error = ?, version = ?,
                    cancel_requested = 1, updated_at = ?, completed_at = ?, expires_at = ?,
                    request_json = ?, runtime_keys_json = ?, runner_id = ?, lease_expires_at = ?,
                    started_at = ?, heartbeat_at = ?
                WHERE task_id = ?
                """,
                (
                    status,
                    _json_dumps(progress),
                    None if status == "cancelled" else _json_dumps(task["result"]),
                    None if status == "cancelled" else task["error"],
                    task["version"] + 1,
                    now,
                    completed_at,
                    expires_at,
                    None if status == "cancelled" else _json_dumps(task["request_payload"]),
                    None if status == "cancelled" else _json_dumps(task["runtime_keys"]),
                    None,
                    None,
                    None if status == "cancelled" else task["started_at"],
                    None if status == "cancelled" else task["heartbeat_at"],
                    task_id,
                ),
            )
        return self.get_task(task_id)

    def is_task_cancel_requested(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        return bool(task and (task["cancel_requested"] or task["status"] == "cancelled"))

    def wait_for_task_update(self, task_id: str, last_version: int, timeout: float = 15.0) -> dict[str, Any] | None:
        deadline = _now_ts() + timeout
        while _now_ts() < deadline:
            task = self.get_task(task_id)
            if task is None:
                return None
            if task["version"] != last_version or task["status"] in {"completed", "failed", "cancelled"}:
                return task
            time.sleep(0.35)
        return self.get_task(task_id)

    def start_context_session(self, owner_id: str, session_id: str, seed: dict[str, Any] | None = None) -> None:
        self.initialize()
        current = self.get_context_session(owner_id, session_id)
        if current:
            return
        payload = {
            "session_id": session_id,
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
            "progress_events": [],
            **deepcopy(seed or {}),
        }
        now = _now_ts()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO travel_context_sessions (
                    session_id, owner_id, payload_json, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    owner_id,
                    _json_dumps(payload),
                    now,
                    now + self._context_ttl_seconds,
                ),
            )

    def publish_context(self, owner_id: str, session_id: str, **sections: Any) -> None:
        self.initialize()
        payload = self.get_context_session(owner_id, session_id) or {
            "session_id": session_id,
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
            "progress_events": [],
        }
        for key, value in sections.items():
            payload[key] = deepcopy(value)
        payload["updated_at"] = _iso_now()
        now = _now_ts()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO travel_context_sessions (
                    session_id, owner_id, payload_json, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    owner_id,
                    _json_dumps(payload),
                    now,
                    now + self._context_ttl_seconds,
                ),
            )

    def append_context_progress(self, owner_id: str, session_id: str, message: str) -> None:
        payload = self.get_context_session(owner_id, session_id) or {
            "session_id": session_id,
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
            "progress_events": [],
        }
        payload.setdefault("progress_events", []).append(message)
        payload["updated_at"] = _iso_now()
        now = _now_ts()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO travel_context_sessions (
                    session_id, owner_id, payload_json, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    owner_id,
                    _json_dumps(payload),
                    now,
                    now + self._context_ttl_seconds,
                ),
            )

    def list_context_sessions(self, owner_id: str) -> list[dict[str, Any]]:
        self.initialize()
        self.prune_expired()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, payload_json
                FROM travel_context_sessions
                WHERE owner_id = ?
                ORDER BY updated_at DESC
                """,
                (owner_id,),
            ).fetchall()
        sessions: list[dict[str, Any]] = []
        for row in rows:
            payload = _json_loads(row["payload_json"], {})
            sessions.append(
                {
                    "session_id": row["session_id"],
                    "created_at": payload.get("created_at", ""),
                    "updated_at": payload.get("updated_at", ""),
                    "destination": (payload.get("trip_request") or {}).get("destination", ""),
                }
            )
        return sessions

    def get_context_session(self, owner_id: str, session_id: str) -> dict[str, Any]:
        self.initialize()
        self.prune_expired()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM travel_context_sessions
                WHERE owner_id = ? AND session_id = ?
                """,
                (owner_id, session_id),
            ).fetchone()
        return _json_loads(row["payload_json"] if row else None, {})

    def read_context_resource(self, owner_id: str, uri: str) -> dict[str, Any]:
        path = uri.replace("travel://", "", 1).strip("/")
        if not path:
            return {"uri": uri, "contents": self.list_context_sessions(owner_id)}
        parts = path.split("/")
        if parts[0] != "sessions":
            return {"uri": uri, "contents": {}}
        if len(parts) == 1:
            return {"uri": uri, "contents": self.list_context_sessions(owner_id)}
        session_id = parts[1]
        session = self.get_context_session(owner_id, session_id)
        if not session:
            return {"uri": uri, "contents": {}}
        if len(parts) == 2:
            return {"uri": uri, "contents": session}
        return {"uri": uri, "contents": session.get(parts[2])}

    def create_static_map_ticket(self, owner_id: str, amap_api_key: str, payload: dict[str, Any]) -> str:
        self.initialize()
        self.prune_expired()
        ticket_id = uuid.uuid4().hex
        now = _now_ts()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO static_map_tickets (
                    ticket_id, owner_id, amap_api_key, payload_json, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    owner_id,
                    amap_api_key,
                    _json_dumps(payload),
                    now,
                    now + self._ticket_ttl_seconds,
                ),
            )
        return ticket_id

    def get_static_map_ticket(self, owner_id: str, ticket_id: str) -> dict[str, Any] | None:
        self.initialize()
        self.prune_expired()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT owner_id, amap_api_key, payload_json, expires_at
                FROM static_map_tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            ).fetchone()
        if row is None or str(row["owner_id"]) != str(owner_id):
            return None
        return {
            "ticket_id": ticket_id,
            "owner_id": row["owner_id"],
            "amap_api_key": row["amap_api_key"],
            "payload": _json_loads(row["payload_json"], {}),
            "expires_at": row["expires_at"],
        }

    def prune_expired(self) -> None:
        self.initialize()
        now = _now_ts()
        with self._connect() as conn:
            conn.execute("DELETE FROM trip_tasks WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
            conn.execute("DELETE FROM travel_context_sessions WHERE expires_at < ?", (now,))
            conn.execute("DELETE FROM static_map_tickets WHERE expires_at < ?", (now,))

    def _transition_task(self, task_id: str, *, status: str, result: Any, error: str | None) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM trip_tasks WHERE task_id = ?", (task_id,)).fetchone()
            task = self._task_from_row(row)
            if not task:
                return None
            now = _now_ts()
            conn.execute(
                """
                UPDATE trip_tasks
                SET status = ?, result_json = ?, error = ?, version = ?, updated_at = ?,
                    completed_at = ?, expires_at = ?, request_json = ?, runtime_keys_json = ?,
                    runner_id = ?, lease_expires_at = ?, heartbeat_at = ?
                WHERE task_id = ?
                """,
                (
                    status,
                    _json_dumps(result) if result is not None else None,
                    error,
                    task["version"] + 1,
                    now,
                    now,
                    now + self._task_retention_seconds,
                    None,
                    None,
                    None,
                    None,
                    None,
                    task_id,
                ),
            )
        return self.get_task(task_id)

    def _task_from_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "task_id": row["task_id"],
            "owner_id": row["owner_id"],
            "status": row["status"],
            "progress_messages": _json_loads(row["progress_json"], []),
            "request_payload": _json_loads(row["request_json"], {}),
            "runtime_keys": _json_loads(row["runtime_keys_json"], {}),
            "result": _json_loads(row["result_json"], None),
            "error": row["error"],
            "version": int(row["version"]),
            "attempts": int(row["attempts"] or 0),
            "cancel_requested": bool(row["cancel_requested"]),
            "runner_id": str(row["runner_id"] or "").strip(),
            "lease_expires_at": float(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None,
            "started_at": float(row["started_at"]) if row["started_at"] is not None else None,
            "heartbeat_at": float(row["heartbeat_at"]) if row["heartbeat_at"] is not None else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "completed_at": float(row["completed_at"]) if row["completed_at"] is not None else None,
            "expires_at": float(row["expires_at"]) if row["expires_at"] is not None else None,
        }

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = {str(row[1]) for row in rows}
        if column not in names:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn


runtime_state_store = RuntimeStateStore()
