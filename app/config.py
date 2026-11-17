"""
Central configuration for the AURO Browser Automation Panel.

Configuration priority:
1. Environment variables
2. SQLite settings table
3. Built-in defaults
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SETTINGS: dict[str, str] = {
    "headless": "false",
    "timeout_ms": "30000",
    "delay_min_ms": "500",
    "delay_max_ms": "2000",
    "retry": "2",
}


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings shared across the project."""

    project_root: Path
    database_path: Path
    tasks_dir: Path
    data_dir: Path
    screenshots_dir: Path
    sessions_dir: Path
    headless: bool
    timeout_ms: int
    delay_min_ms: int
    delay_max_ms: int
    retry: int
    # Web/Docker defaults to installed Chrome; desktop can bundle Chromium.
    browser_channel: str = "chrome"


def resolve_path(environment_name: str, default_path: Path) -> Path:
    raw_path = os.getenv(environment_name)
    path = Path(raw_path).expanduser() if raw_path else default_path
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def parse_bool(value: str, setting_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {setting_name}: {value!r}")


def parse_int(value: str, setting_name: str, minimum: int = 0) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise ValueError(
            f"{setting_name} must be an integer; received {value!r}."
        ) from exc
    if result < minimum:
        raise ValueError(f"{setting_name} must be at least {minimum}.")
    return result


def read_database_settings(database_path: Path) -> dict[str, str]:
    if not database_path.is_file():
        return {}
    try:
        with sqlite3.connect(database_path, timeout=2) as connection:
            table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'settings'
                """
            ).fetchone()
            if table is None:
                return {}
            rows = connection.execute(
                "SELECT key, value FROM settings"
            ).fetchall()
            return {str(key): str(value) for key, value in rows}
    except sqlite3.Error as exc:
        raise RuntimeError(
            f"Unable to read settings from {database_path}: {exc}"
        ) from exc


def get_raw_setting(
    environment_name: str,
    database_name: str,
    database_settings: dict[str, str],
    default: str,
) -> str:
    environment_value = os.getenv(environment_name)
    if environment_value is not None:
        return environment_value
    if database_name in database_settings:
        return database_settings[database_name]
    return default


def load_settings() -> Settings:
    database_path = resolve_path(
        "DATABASE_PATH",
        PROJECT_ROOT / "data" / "automation.db",
    )
    database_settings = read_database_settings(database_path)

    tasks_dir = resolve_path("TASKS_DIR", PROJECT_ROOT / "app" / "tasks")
    data_dir = resolve_path("DATA_DIR", PROJECT_ROOT / "data")
    screenshots_dir = resolve_path("SCREENSHOTS_DIR", PROJECT_ROOT / "screenshots")
    sessions_dir = resolve_path("SESSIONS_DIR", PROJECT_ROOT / "sessions")

    headless = parse_bool(
        get_raw_setting(
            "AUTOMATION_HEADLESS", "headless", database_settings,
            DEFAULT_SETTINGS["headless"],
        ),
        "AUTOMATION_HEADLESS",
    )
    timeout_ms = parse_int(
        get_raw_setting(
            "AUTOMATION_TIMEOUT_MS", "timeout_ms", database_settings,
            DEFAULT_SETTINGS["timeout_ms"],
        ),
        "AUTOMATION_TIMEOUT_MS",
        minimum=1,
    )
    delay_min_ms = parse_int(
        get_raw_setting(
            "AUTOMATION_DELAY_MIN_MS", "delay_min_ms", database_settings,
            DEFAULT_SETTINGS["delay_min_ms"],
        ),
        "AUTOMATION_DELAY_MIN_MS",
    )
    delay_max_ms = parse_int(
        get_raw_setting(
            "AUTOMATION_DELAY_MAX_MS", "delay_max_ms", database_settings,
            DEFAULT_SETTINGS["delay_max_ms"],
        ),
        "AUTOMATION_DELAY_MAX_MS",
    )
    if delay_min_ms > delay_max_ms:
        raise ValueError(
            "AUTOMATION_DELAY_MIN_MS cannot exceed AUTOMATION_DELAY_MAX_MS."
        )
    retry = parse_int(
        get_raw_setting(
            "AUTOMATION_RETRY", "retry", database_settings,
            DEFAULT_SETTINGS["retry"],
        ),
        "AUTOMATION_RETRY",
    )

    browser_channel = os.getenv(
        "AUTOMATION_BROWSER_CHANNEL", "chrome"
    ).strip().lower()
    if browser_channel not in {"chrome", "chromium"}:
        raise ValueError(
            "AUTOMATION_BROWSER_CHANNEL must be either 'chrome' or 'chromium'."
        )

    return Settings(
        project_root=PROJECT_ROOT,
        database_path=database_path,
        tasks_dir=tasks_dir,
        data_dir=data_dir,
        screenshots_dir=screenshots_dir,
        sessions_dir=sessions_dir,
        headless=headless,
        timeout_ms=timeout_ms,
        delay_min_ms=delay_min_ms,
        delay_max_ms=delay_max_ms,
        retry=retry,
        browser_channel=browser_channel,
    )


def ensure_runtime_directories(settings: Settings | None = None) -> None:
    config = settings or load_settings()
    directories = (
        config.database_path.parent,
        config.tasks_dir,
        config.data_dir,
        config.screenshots_dir,
        config.sessions_dir,
    )
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
