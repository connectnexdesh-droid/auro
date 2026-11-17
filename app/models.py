"""
Typed data models used by the AURO database layer.

These dataclasses are plain Python objects. They do not require an ORM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """A YAML task registered in the local database."""

    id: int
    name: str
    path: str
    last_run_status: str | None
    last_run_at: str | None

    @classmethod
    def from_row(cls, row: Any) -> "TaskRecord":
        """Create a TaskRecord from a sqlite3.Row or mapping."""
        return cls(
            id=int(row["id"]),
            name=str(row["name"]),
            path=str(row["path"]),
            last_run_status=row["last_run_status"],
            last_run_at=row["last_run_at"],
        )


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Execution metadata for one automation run."""

    id: str
    task_name: str
    status: str
    started_at: str
    finished_at: str | None
    error: str | None
    screenshot_dir: str | None

    @classmethod
    def from_row(cls, row: Any) -> "RunRecord":
        """Create a RunRecord from a sqlite3.Row or mapping."""
        return cls(
            id=str(row["id"]),
            task_name=str(row["task_name"]),
            status=str(row["status"]),
            started_at=str(row["started_at"]),
            finished_at=row["finished_at"],
            error=row["error"],
            screenshot_dir=row["screenshot_dir"],
        )


@dataclass(frozen=True, slots=True)
class LogRecord:
    """One structured log entry associated with a run."""

    id: int
    run_id: str
    level: str
    message: str
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> "LogRecord":
        """Create a LogRecord from a sqlite3.Row or mapping."""
        return cls(
            id=int(row["id"]),
            run_id=str(row["run_id"]),
            level=str(row["level"]),
            message=str(row["message"]),
            created_at=str(row["created_at"]),
        )


@dataclass(frozen=True, slots=True)
class SettingRecord:
    """One application setting stored as text in SQLite."""

    key: str
    value: str
