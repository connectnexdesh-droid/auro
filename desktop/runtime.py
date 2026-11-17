"""Runtime paths and first-launch preparation for the AURO desktop app."""
from __future__ import annotations

import os
import shutil
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import MutableMapping


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    bundle_root: Path
    app_data_dir: Path
    database_path: Path
    tasks_dir: Path
    data_dir: Path
    screenshots_dir: Path
    sessions_dir: Path
    logs_dir: Path
    browser_path: Path | None


def default_bundle_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[1]


def default_app_data_dir(
    environ: MutableMapping[str, str] | None = None,
) -> Path:
    env = environ if environ is not None else os.environ
    local_app_data = env.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data).expanduser() / "AURO"
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "AURO"
    return Path.home() / ".local" / "share" / "AURO"


def _seed_task_files(source: Path, destination: Path) -> None:
    """Copy bundled starter workflows without overwriting user edits."""
    if not source.is_dir():
        raise FileNotFoundError(f"Bundled AURO tasks folder is missing: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.yaml", "*.yml"):
        for source_file in source.glob(pattern):
            target_file = destination / source_file.name
            if not target_file.exists():
                shutil.copy2(source_file, target_file)


def configure_runtime(
    *,
    bundle_root: Path | None = None,
    app_data_dir: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> RuntimePaths:
    """Configure persistent desktop paths before importing app.main."""
    env = environ if environ is not None else os.environ
    root = (bundle_root or default_bundle_root()).resolve()
    user_data = (app_data_dir or default_app_data_dir(env)).resolve()

    database_path = user_data / "data" / "automation.db"
    tasks_dir = user_data / "tasks"
    data_dir = user_data / "data"
    screenshots_dir = user_data / "screenshots"
    sessions_dir = user_data / "sessions"
    logs_dir = user_data / "logs"

    for directory in (
        user_data, database_path.parent, tasks_dir, data_dir,
        screenshots_dir, sessions_dir, logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    _seed_task_files(root / "app" / "tasks", tasks_dir)

    env["DATABASE_PATH"] = str(database_path)
    env["TASKS_DIR"] = str(tasks_dir)
    env["DATA_DIR"] = str(data_dir)
    env["SCREENSHOTS_DIR"] = str(screenshots_dir)
    env["SESSIONS_DIR"] = str(sessions_dir)
    env["AUTOMATION_BROWSER_CHANNEL"] = "chromium"

    browser_path = root / "ms-playwright"
    if not browser_path.is_dir():
        development_browser_path = root / ".playwright-browsers"
        browser_path = (
            development_browser_path
            if development_browser_path.is_dir()
            else None
        )
    if browser_path is not None:
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_path)

    return RuntimePaths(
        bundle_root=root,
        app_data_dir=user_data,
        database_path=database_path,
        tasks_dir=tasks_dir,
        data_dir=data_dir,
        screenshots_dir=screenshots_dir,
        sessions_dir=sessions_dir,
        logs_dir=logs_dir,
        browser_path=browser_path,
    )
