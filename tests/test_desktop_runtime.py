"""Tests for AURO desktop runtime paths and first-launch seeding."""
from __future__ import annotations

from pathlib import Path

from desktop.runtime import configure_runtime


def test_desktop_runtime_uses_user_data_and_seeds_starter_workflows(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    source_tasks = bundle / "app" / "tasks"
    source_tasks.mkdir(parents=True)
    (source_tasks / "starter.yaml").write_text(
        "name: starter\nsteps:\n  - action: goto\n    url: https://example.com\n",
        encoding="utf-8",
    )
    browsers = bundle / "ms-playwright"
    browsers.mkdir()

    user_data = tmp_path / "local" / "AURO"
    environment: dict[str, str] = {}
    paths = configure_runtime(
        bundle_root=bundle,
        app_data_dir=user_data,
        environ=environment,
    )

    assert paths.database_path == user_data / "data" / "automation.db"
    assert paths.tasks_dir == user_data / "tasks"
    assert paths.screenshots_dir == user_data / "screenshots"
    assert paths.sessions_dir == user_data / "sessions"
    assert paths.logs_dir == user_data / "logs"
    assert paths.browser_path == browsers
    assert (paths.tasks_dir / "starter.yaml").is_file()
    assert environment["DATABASE_PATH"] == str(paths.database_path)
    assert environment["TASKS_DIR"] == str(paths.tasks_dir)
    assert environment["AUTOMATION_BROWSER_CHANNEL"] == "chromium"
    assert environment["PLAYWRIGHT_BROWSERS_PATH"] == str(browsers)


def test_desktop_runtime_never_overwrites_existing_user_workflows(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    source_tasks = bundle / "app" / "tasks"
    source_tasks.mkdir(parents=True)
    (source_tasks / "demo.yaml").write_text("name: bundled\n", encoding="utf-8")

    user_data = tmp_path / "local" / "AURO"
    existing_tasks = user_data / "tasks"
    existing_tasks.mkdir(parents=True)
    user_file = existing_tasks / "demo.yaml"
    user_file.write_text("name: my_custom_workflow\n", encoding="utf-8")

    configure_runtime(
        bundle_root=bundle,
        app_data_dir=user_data,
        environ={},
    )
    assert user_file.read_text(encoding="utf-8") == "name: my_custom_workflow\n"
