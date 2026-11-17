"""
Smoke and unit tests for the AURO browser automation runner.

Run from the repository root:
    pytest -v

The demo-form test requires the installed Google Chrome channel and
network access to https://www.selenium.dev.
"""

from __future__ import annotations

import csv
import re

from datetime import datetime
from pathlib import Path

import pytest

from app.runner import (
    TaskValidationError,
    load_input_records,
    load_task,
    resolve_templates,
    run_task,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_TASK = PROJECT_ROOT / "app" / "tasks" / "demo_form.yaml"


@pytest.fixture
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """
    Redirect runtime files to pytest's temporary directory.

    Tests therefore never overwrite the developer's real database,
    screenshots, uploaded data, or saved browser sessions.
    """

    paths = {
        "database": tmp_path / "automation-test.db",
        "data": tmp_path / "data",
        "screenshots": tmp_path / "screenshots",
        "sessions": tmp_path / "sessions",
        "tasks": tmp_path / "tasks",
    }

    environment = {
        "DATABASE_PATH": paths["database"],
        "DATA_DIR": paths["data"],
        "SCREENSHOTS_DIR": paths["screenshots"],
        "SESSIONS_DIR": paths["sessions"],
        "TASKS_DIR": paths["tasks"],
        "AUTOMATION_HEADLESS": "true",
        "AUTOMATION_DELAY_MIN_MS": "0",
        "AUTOMATION_DELAY_MAX_MS": "0",
        "AUTOMATION_RETRY": "0",
    }

    for key, value in environment.items():
        monkeypatch.setenv(key, str(value))

    return paths


def test_load_demo_task_and_validate_steps() -> None:
    """The committed demo YAML should load and contain supported steps."""

    task = load_task(DEMO_TASK)

    assert task["name"] == "demo_form"
    assert task["headless"] is False
    assert task["retry"] == 2
    assert task["steps"]
    assert task["_source_path"] == str(DEMO_TASK.resolve())


def test_template_engine_resolves_csv_line_random_and_now() -> None:
    """All four supported value placeholders should be resolved."""

    record = {
        "first_name": "Amina",
        "email": "amina@example.com",
        "line": "A text input line",
    }

    resolved = resolve_templates(
        {
            "name": "{{csv.first_name}}",
            "email": "{{csv.email}}",
            "text": "{{line}}",
            "generated": "{{random}}",
            "created_at": "{{now}}",
            "literal": "Hello AURO",
            "nested": ["{{csv.first_name}}", "{{random}}"],
        },
        record,
    )

    assert resolved["name"] == "Amina"
    assert resolved["email"] == "amina@example.com"
    assert resolved["text"] == "A text input line"
    assert re.fullmatch(r"[A-Za-z0-9]{8}", resolved["generated"])
    assert isinstance(datetime.fromisoformat(resolved["created_at"]), datetime)
    assert resolved["literal"] == "Hello AURO"
    assert resolved["nested"][0] == "Amina"
    assert re.fullmatch(r"[A-Za-z0-9]{8}", resolved["nested"][1])


def test_template_engine_rejects_missing_csv_column() -> None:
    """A misspelled CSV column should fail clearly rather than silently."""

    with pytest.raises(ValueError, match="CSV column 'missing'"):
        resolve_templates("{{csv.missing}}", {"first_name": "Amina"})


def test_template_engine_rejects_line_without_txt_record() -> None:
    """The TXT placeholder must have a line value in its record."""

    with pytest.raises(ValueError, match="current input is not a TXT line"):
        resolve_templates("{{line}}", {"first_name": "Amina"})


def test_csv_input_reader(tmp_path: Path) -> None:
    """CSV input should return one mapping per data row."""

    csv_path = tmp_path / "contacts.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["name", "email"])
        writer.writeheader()
        writer.writerow({"name": "Amina", "email": "amina@example.com"})
        writer.writerow({"name": "Rafi", "email": "rafi@example.com"})

    records = load_input_records(csv_path)

    assert records == [
        {"name": "Amina", "email": "amina@example.com"},
        {"name": "Rafi", "email": "rafi@example.com"},
    ]


def test_txt_input_reader(tmp_path: Path) -> None:
    """TXT input should return non-empty lines as line template records."""

    txt_path = tmp_path / "names.txt"
    txt_path.write_text("Amina\n\nRafi\n", encoding="utf-8")

    assert load_input_records(txt_path) == [
        {"line": "Amina"},
        {"line": "Rafi"},
    ]


def test_unsupported_action_is_rejected(tmp_path: Path) -> None:
    """Unknown YAML actions must be rejected before launching a browser."""

    task_path = tmp_path / "invalid.yaml"
    task_path.write_text(
        """
name: invalid_task
steps:
  - action: execute_shell
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(TaskValidationError, match="unsupported action"):
        load_task(task_path)


@pytest.mark.asyncio
async def test_demo_form_runs_headless_and_produces_screenshot(
    isolated_runtime: dict[str, Path],
) -> None:
    """
    Run the real Selenium demo form in headless installed Chrome.

    This is an end-to-end smoke test. It requires Chrome to be installed
    using the Playwright Chrome installation command and network access.
    """

    result = await run_task(DEMO_TASK, headless=True)

    assert result["status"] == "completed", result.get("error")
    assert result["task_name"] == "demo_form"
    assert result["error"] is None
    assert result["attempts"] == 1
    assert result["screenshots"], "The workflow did not report a screenshot."

    screenshot_paths = [
        isolated_runtime["screenshots"] / item["filename"]
        for item in result["screenshots"]
    ]

    assert any(path.is_file() for path in screenshot_paths), (
        "The demo task completed but no screenshot file was created."
    )
    assert all(
        path.stat().st_size > 0
        for path in screenshot_paths
        if path.is_file()
    )
