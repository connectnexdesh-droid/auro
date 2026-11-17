"""
SQLite persistence layer for AURO.

The project deliberately uses Python's built-in sqlite3 module:
there is no ORM and no external database server to configure.
"""

from __future__ import annotations

import sqlite3
import uuid

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.config import DEFAULT_SETTINGS, load_settings
from app.models import LogRecord, RunRecord, TaskRecord


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with timezone information."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _database_path(path: str | Path | None = None) -> Path:
    """Resolve the database path from an argument or application config."""
    if path is not None:
        return Path(path).expanduser().resolve()
    return load_settings().database_path


@contextmanager
def _connect(
    path: str | Path | None = None,
) -> Iterator[sqlite3.Connection]:
    """
    Open a SQLite connection with safe defaults.

    The connection is committed on success and rolled back on error.
    Rows can be accessed by column name.
    """

    database_path = _database_path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        database_path,
        timeout=30,
        isolation_level="DEFERRED",
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(path: str | Path | None = None) -> None:
    """
    Create all application tables and insert default settings.

    Safe to call repeatedly. Existing data is preserved.
    An optional path is useful for isolated tests.
    """

    with _connect(path) as connection:
        # WAL improves read/write concurrency for dashboard polling.
        connection.execute("PRAGMA journal_mode = WAL")

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                path TEXT NOT NULL,
                last_run_status TEXT,
                last_run_at TEXT
            );

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                task_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT,
                screenshot_dir TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_runs_task_started
                ON runs(task_name, started_at DESC);

            CREATE TABLE IF NOT EXISTS run_progress (
                run_id TEXT PRIMARY KEY,
                total_steps INTEGER NOT NULL DEFAULT 0,
                completed_steps INTEGER NOT NULL DEFAULT 0,
                current_step INTEGER NOT NULL DEFAULT 0,
                current_action TEXT,
                record_index INTEGER NOT NULL DEFAULT 0,
                total_records INTEGER NOT NULL DEFAULT 0,
                attempt INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS run_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                attempt INTEGER NOT NULL,
                record_index INTEGER NOT NULL,
                step_index INTEGER NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms INTEGER,
                error TEXT,
                UNIQUE(run_id, sequence),
                FOREIGN KEY (run_id) REFERENCES runs(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_run_steps_run_sequence
                ON run_steps(run_id, sequence ASC);

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_logs_run_created
                ON logs(run_id, created_at ASC);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        # Insert defaults only when a key does not already exist.
        connection.executemany(
            """
            INSERT OR IGNORE INTO settings (key, value)
            VALUES (?, ?)
            """,
            DEFAULT_SETTINGS.items(),
        )


def register_task(name: str, path: str | Path) -> TaskRecord:
    """
    Insert or update a task's YAML file path.

    Existing run history and last-run metadata are preserved.
    """

    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Task name cannot be empty.")

    task_path = str(Path(path).resolve())

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO tasks (name, path)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET path = excluded.path
            """,
            (clean_name, task_path),
        )

        row = connection.execute(
            "SELECT * FROM tasks WHERE name = ?",
            (clean_name,),
        ).fetchone()

    return TaskRecord.from_row(row)


def get_tasks() -> list[TaskRecord]:
    """Return all registered tasks ordered by name."""

    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM tasks ORDER BY name ASC"
        ).fetchall()

    return [TaskRecord.from_row(row) for row in rows]


def get_task(name: str) -> TaskRecord | None:
    """Return one registered task, or None if it does not exist."""

    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE name = ?",
            (name,),
        ).fetchone()

    return TaskRecord.from_row(row) if row else None


def create_run(
    task_name: str,
    screenshot_dir: str | Path | None = None,
) -> str:
    """
    Create a run in 'running' state and return its unique ID.

    A UUID is used so IDs remain unique across processes and machines.
    """

    clean_name = task_name.strip()
    if not clean_name:
        raise ValueError("Task name cannot be empty.")

    run_id = uuid.uuid4().hex
    started_at = utc_now()
    directory = str(Path(screenshot_dir).resolve()) if screenshot_dir else None

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO runs (
                id, task_name, status, started_at, screenshot_dir
            )
            VALUES (?, ?, 'running', ?, ?)
            """,
            (run_id, clean_name, started_at, directory),
        )

    return run_id


def finish_run(
    run_id: str,
    status: str,
    error: str | None = None,
    screenshot_dir: str | Path | None = None,
) -> None:
    """
    Mark a run as completed, failed, or cancelled.

    The corresponding task's last-run fields are updated as well.
    """

    allowed_statuses = {"completed", "success", "failed", "cancelled"}
    normalized_status = status.strip().lower()

    if normalized_status not in allowed_statuses:
        raise ValueError(
            f"Unsupported final run status: {status!r}"
        )

    finished_at = utc_now()
    directory = str(Path(screenshot_dir).resolve()) if screenshot_dir else None

    with _connect() as connection:
        row = connection.execute(
            "SELECT task_name FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

        if row is None:
            raise ValueError(f"Run not found: {run_id}")

        connection.execute(
            """
            UPDATE runs
            SET status = ?,
                finished_at = ?,
                error = ?,
                screenshot_dir = COALESCE(?, screenshot_dir)
            WHERE id = ?
            """,
            (normalized_status, finished_at, error, directory, run_id),
        )

        connection.execute(
            """
            UPDATE tasks
            SET last_run_status = ?, last_run_at = ?
            WHERE name = ?
            """,
            (normalized_status, finished_at, row["task_name"]),
        )

        # A cancelled or failed run must not leave an action marked as running.
        if normalized_status in {"failed", "cancelled"}:
            connection.execute(
                """
                UPDATE run_steps
                SET status = ?, finished_at = ?, error = COALESCE(error, ?)
                WHERE run_id = ? AND status = 'running'
                """,
                (
                    normalized_status,
                    finished_at,
                    error or normalized_status.title(),
                    run_id,
                ),
            )

        progress_status = (
            "Completed" if normalized_status in {"completed", "success"}
            else normalized_status.title()
        )
        connection.execute(
            """
            UPDATE run_progress
            SET completed_steps = CASE
                    WHEN ? IN ('completed', 'success') THEN total_steps
                    ELSE completed_steps
                END,
                current_step = CASE
                    WHEN ? IN ('completed', 'success') THEN total_steps
                    ELSE current_step
                END,
                current_action = ?,
                updated_at = ?
            WHERE run_id = ?
            """,
            (
                normalized_status,
                normalized_status,
                progress_status,
                finished_at,
                run_id,
            ),
        )


def log(run_id: str, level: str, message: str) -> int:
    """
    Store one log message and return its database ID.

    The run must exist so logs cannot become orphaned.
    """

    normalized_level = level.strip().upper()
    if not normalized_level:
        raise ValueError("Log level cannot be empty.")

    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO logs (run_id, level, message, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, normalized_level, str(message), utc_now()),
        )
        return int(cursor.lastrowid)


def get_recent_runs(
    task_name: str,
    limit: int = 20,
) -> list[RunRecord]:
    """Return the newest runs for a task."""

    if limit < 1:
        raise ValueError("limit must be at least 1.")

    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM runs
            WHERE task_name = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (task_name, limit),
        ).fetchall()

    return [RunRecord.from_row(row) for row in rows]


def get_run(run_id: str) -> RunRecord | None:
    """Return one run by its ID."""

    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

    return RunRecord.from_row(row) if row else None


def get_run_logs(run_id: str, limit: int = 500) -> list[LogRecord]:
    """Return log entries for a run, oldest first."""

    if limit < 1:
        raise ValueError("limit must be at least 1.")

    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM logs
            WHERE run_id = ?
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()

    return [LogRecord.from_row(row) for row in rows]


def get_setting(key: str) -> str | None:
    """Read a setting; return None if the key does not exist."""

    with _connect() as connection:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()

    return str(row["value"]) if row else None


def set_setting(key: str, value: str) -> None:
    """Insert or update one application setting."""

    clean_key = key.strip()
    if not clean_key:
        raise ValueError("Setting key cannot be empty.")

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (clean_key, str(value)),
        )

def initialize_run_progress(
    run_id: str,
    *,
    total_steps: int,
    total_records: int,
) -> None:
    """Create or reset the progress summary for a newly-started run."""

    if total_steps < 0 or total_records < 0:
        raise ValueError("Progress totals cannot be negative.")

    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO run_progress (
                run_id, total_steps, completed_steps, current_step,
                current_action, record_index, total_records, attempt, updated_at
            )
            VALUES (?, ?, 0, 0, 'Preparing workflow', 0, ?, 1, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                total_steps = excluded.total_steps,
                completed_steps = 0,
                current_step = 0,
                current_action = 'Preparing workflow',
                record_index = 0,
                total_records = excluded.total_records,
                attempt = 1,
                updated_at = excluded.updated_at
            """,
            (run_id, total_steps, total_records, utc_now()),
        )


def reset_run_progress(run_id: str, attempt: int) -> None:
    """Reset the live progress counters when a retry starts."""

    if attempt < 1:
        raise ValueError("Attempt number must be at least 1.")

    with _connect() as connection:
        connection.execute(
            """
            UPDATE run_progress
            SET completed_steps = 0,
                current_step = 0,
                current_action = 'Starting browser',
                record_index = 0,
                attempt = ?,
                updated_at = ?
            WHERE run_id = ?
            """,
            (attempt, utc_now(), run_id),
        )


def start_run_step(
    run_id: str,
    *,
    attempt: int,
    record_index: int,
    step_index: int,
    global_step: int,
    action: str,
) -> int:
    """Add a running action to the timeline and update the live step label."""

    if min(attempt, record_index, step_index, global_step) < 1:
        raise ValueError("Attempt and step positions must be positive.")

    started_at = utc_now()
    with _connect() as connection:
        sequence_row = connection.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
            FROM run_steps
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        sequence = int(sequence_row["next_sequence"])

        cursor = connection.execute(
            """
            INSERT INTO run_steps (
                run_id, sequence, attempt, record_index, step_index,
                action, status, started_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'running', ?)
            """,
            (
                run_id,
                sequence,
                attempt,
                record_index,
                step_index,
                action,
                started_at,
            ),
        )
        connection.execute(
            """
            UPDATE run_progress
            SET current_step = ?,
                current_action = ?,
                record_index = ?,
                attempt = ?,
                updated_at = ?
            WHERE run_id = ?
            """,
            (
                global_step,
                action,
                record_index,
                attempt,
                started_at,
                run_id,
            ),
        )
        return int(cursor.lastrowid)


def finish_run_step(
    step_id: int,
    *,
    status: str,
    duration_ms: int,
    completed_steps: int | None = None,
    error: str | None = None,
) -> None:
    """Finish one timeline action and persist its measured duration."""

    normalized_status = status.strip().lower()
    if normalized_status not in {"completed", "failed", "cancelled"}:
        raise ValueError(f"Unsupported step status: {status!r}")

    finished_at = utc_now()
    safe_duration = max(0, int(duration_ms))

    with _connect() as connection:
        row = connection.execute(
            "SELECT run_id FROM run_steps WHERE id = ?",
            (step_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Run step not found: {step_id}")

        connection.execute(
            """
            UPDATE run_steps
            SET status = ?, finished_at = ?, duration_ms = ?, error = ?
            WHERE id = ?
            """,
            (normalized_status, finished_at, safe_duration, error, step_id),
        )

        if normalized_status == "completed" and completed_steps is not None:
            connection.execute(
                """
                UPDATE run_progress
                SET completed_steps = MAX(completed_steps, ?),
                    updated_at = ?
                WHERE run_id = ?
                """,
                (max(0, int(completed_steps)), finished_at, row["run_id"]),
            )


def get_run_progress(run_id: str) -> dict[str, object] | None:
    """Return the current progress counters for one run."""

    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM run_progress WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    return dict(row) if row else None


def get_run_steps(run_id: str, limit: int = 2000) -> list[dict[str, object]]:
    """Return the run's action timeline in execution order."""

    if limit < 1:
        raise ValueError("limit must be at least 1.")

    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, sequence, attempt, record_index, step_index, action,
                   status, started_at, finished_at, duration_ms, error
            FROM run_steps
            WHERE run_id = ?
            ORDER BY sequence ASC
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]

