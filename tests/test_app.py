"""Integration smoke tests for the AURO dashboard and its HTTP routes."""

from __future__ import annotations

import asyncio
import base64
import importlib
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Start an isolated AURO app with temporary runtime storage."""

    project_root = Path(__file__).resolve().parents[1]
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    shutil.copy2(
        project_root / "app" / "tasks" / "demo_form.yaml",
        tasks_dir / "demo_form.yaml",
    )

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "data" / "automation.db"))
    monkeypatch.setenv("TASKS_DIR", str(tasks_dir))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SCREENSHOTS_DIR", str(tmp_path / "screenshots"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.delenv("AUTOMATION_HEADLESS", raising=False)
    monkeypatch.delenv("AUTOMATION_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("AUTOMATION_DELAY_MIN_MS", raising=False)
    monkeypatch.delenv("AUTOMATION_DELAY_MAX_MS", raising=False)
    monkeypatch.delenv("AUTOMATION_RETRY", raising=False)

    import app.main as main_module

    main_module = importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        yield client, main_module, tmp_path


def test_dashboard_task_detail_and_settings_pages_render(app_client) -> None:
    client, _, _ = app_client

    dashboard = client.get("/")
    detail = client.get("/task/demo_form")
    settings = client.get("/settings")
    health = client.get("/health")

    assert dashboard.status_code == 200
    assert "Dashboard" in dashboard.text
    assert "demo_form" in dashboard.text

    assert detail.status_code == 200
    assert "Edit YAML" in detail.text
    assert "Start automation" in detail.text

    assert settings.status_code == 200
    assert "Headless browser" in settings.text

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "auro"}


def test_dashboard_can_create_task_and_upload_csv(app_client) -> None:
    client, _, tmp_path = app_client

    task_yaml = (
        'name: quick_check\n'
        'description: "Dashboard-created test task"\n'
        'headless: true\n'
        'steps:\n'
        '  - action: goto\n'
        '    url: "https://example.com"\n'
    )
    created = client.post(
        "/tasks/create",
        data={"name": "quick_check", "yaml_content": task_yaml},
        follow_redirects=False,
    )

    assert created.status_code == 303
    assert created.headers["location"] == "/task/quick_check"
    assert client.get("/task/quick_check").status_code == 200
    assert (tmp_path / "tasks" / "quick_check.yaml").is_file()

    uploaded = client.post(
        "/upload",
        files={
            "file": (
                "contacts.csv",
                b"first_name,email\nAmina,amina@example.com\n",
                "text/csv",
            )
        },
    )

    assert uploaded.status_code == 201
    filename = uploaded.json()["filename"]
    assert filename.endswith(".csv")
    assert (tmp_path / "data" / filename).read_bytes().startswith(b"first_name,email")


def test_dashboard_settings_are_saved_to_sqlite(app_client) -> None:
    client, main_module, _ = app_client

    saved = client.post(
        "/settings",
        data={
            "headless": "true",
            "delay_min_ms": "250",
            "delay_max_ms": "750",
            "retry": "1",
            "timeout_ms": "45000",
        },
        follow_redirects=False,
    )

    assert saved.status_code == 303
    assert saved.headers["location"] == "/settings?saved=1"
    assert main_module.database.get_setting("headless") == "true"
    assert main_module.database.get_setting("delay_min_ms") == "250"
    assert main_module.database.get_setting("delay_max_ms") == "750"
    assert main_module.database.get_setting("retry") == "1"
    assert main_module.database.get_setting("timeout_ms") == "45000"


def test_run_status_logs_and_screenshot_gallery(app_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, main_module, tmp_path = app_client

    async def fake_background_run(
        task_path: str,
        run_id: str,
        input_path: str | None = None,
    ) -> None:
        main_module.database.log(run_id, "INFO", "Dashboard test run started.")
        main_module.database.initialize_run_progress(
            run_id,
            total_steps=2,
            total_records=1,
        )
        main_module.database.reset_run_progress(run_id, 1)

        first_step = main_module.database.start_run_step(
            run_id,
            attempt=1,
            record_index=1,
            step_index=1,
            global_step=1,
            action="goto",
        )
        main_module.database.finish_run_step(
            first_step,
            status="completed",
            duration_ms=120,
            completed_steps=1,
        )

        second_step = main_module.database.start_run_step(
            run_id,
            attempt=1,
            record_index=1,
            step_index=2,
            global_step=2,
            action="click",
        )
        main_module.database.finish_run_step(
            second_step,
            status="completed",
            duration_ms=80,
            completed_steps=2,
        )
        main_module.database.finish_run(
            run_id,
            "completed",
            screenshot_dir=tmp_path / "screenshots",
        )
        main_module.database.log(run_id, "INFO", "Dashboard test run completed.")

    monkeypatch.setattr(main_module, "_execute_background_run", fake_background_run)

    started = client.post("/task/demo_form/run", data={})
    assert started.status_code == 202
    run_id = started.json()["run_id"]

    status = client.get(f"/task/demo_form/status/{run_id}")
    assert status.status_code == 200
    status_data = status.json()
    assert status_data["status"] == "completed"
    assert status_data["total_steps"] == 2
    assert status_data["completed_steps"] == 2
    assert status_data["progress_percent"] == 100
    assert status_data["elapsed_seconds"] >= 0
    assert status_data["expected_finish_at"] is None
    assert [step["action"] for step in status_data["timeline"]] == ["goto", "click"]
    assert [step["status"] for step in status_data["timeline"]] == [
        "completed",
        "completed",
    ]
    assert [step["duration_ms"] for step in status_data["timeline"]] == [120, 80]

    logs = client.get(f"/task/demo_form/logs/{run_id}")
    assert logs.status_code == 200
    messages = [entry["message"] for entry in logs.json()["logs"]]
    assert "Dashboard test run started." in messages
    assert "Dashboard test run completed." in messages

    screenshots_dir = tmp_path / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    screenshot_name = f"demo_form_{run_id}_1.png"
    screenshot_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/"
        "lWQAAAAASUVORK5CYII="
    )
    (screenshots_dir / screenshot_name).write_bytes(screenshot_bytes)

    gallery = client.get(f"/task/demo_form/screenshots/{run_id}")
    assert gallery.status_code == 200
    screenshot = gallery.json()["screenshots"][0]
    assert screenshot["filename"] == screenshot_name

    image_response = client.get(screenshot["url"])
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/png")

    detail = client.get("/task/demo_form")
    assert detail.status_code == 200
    assert "Elapsed" in detail.text
    assert "data-progress-elapsed" in detail.text
    assert "data-step-action" in detail.text
    assert "data-step-meta" in detail.text
    assert "data-step-error" in detail.text
    assert "data-step-result" in detail.text


def test_running_eta_uses_measured_action_durations_and_retry_fallback(app_client) -> None:
    client, main_module, _ = app_client
    database = main_module.database
    run_id = database.create_run("demo_form")

    database.initialize_run_progress(
        run_id,
        total_steps=4,
        total_records=1,
    )
    database.reset_run_progress(run_id, 1)

    for index, duration_ms in enumerate((2000, 4000), start=1):
        step_id = database.start_run_step(
            run_id,
            attempt=1,
            record_index=1,
            step_index=index,
            global_step=index,
            action="click",
        )
        database.finish_run_step(
            step_id,
            status="completed",
            duration_ms=duration_ms,
            completed_steps=index,
        )

    # A retry resets progress. ETA should fall back to the last attempt's
    # measured action durations instead of dividing total elapsed time.
    database.reset_run_progress(run_id, 2)
    status = client.get(f"/task/demo_form/status/{run_id}").json()
    assert status["attempt"] == 2
    assert status["completed_steps"] == 0
    assert status["estimated_remaining_seconds"] == 12
    assert status["expected_finish_at"] is not None

    # Once the new attempt completes an action, its own measurements take
    # precedence over the previous attempt's timing samples.
    step_id = database.start_run_step(
        run_id,
        attempt=2,
        record_index=1,
        step_index=1,
        global_step=1,
        action="goto",
    )
    database.finish_run_step(
        step_id,
        status="completed",
        duration_ms=5000,
        completed_steps=1,
    )
    status = client.get(f"/task/demo_form/status/{run_id}").json()
    assert status["completed_steps"] == 1
    assert status["estimated_remaining_seconds"] == 15


def test_stop_request_cancels_a_queued_run(app_client) -> None:
    client, main_module, tmp_path = app_client
    task = main_module.database.get_task("demo_form")
    assert task is not None

    run_id = main_module.database.create_run(
        "demo_form",
        screenshot_dir=tmp_path / "screenshots",
    )

    stopped = client.post(f"/task/demo_form/stop/{run_id}")
    assert stopped.status_code == 202
    assert stopped.json()["status"] == "cancelling"
    assert run_id in main_module._CANCEL_REQUESTED

    asyncio.run(main_module._execute_background_run(task.path, run_id))

    status = client.get(f"/task/demo_form/status/{run_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "cancelled"
    assert run_id not in main_module._CANCEL_REQUESTED
