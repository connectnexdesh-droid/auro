"""Real-browser end-to-end smoke test for the AURO dashboard."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BASE_TIMEOUT_MS = 15_000


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_server(url: str, process: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + 45

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "AURO web server exited before becoming ready:\n"
                + log_path.read_text(encoding="utf-8", errors="replace")
            )

        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)

    raise TimeoutError(
        "AURO web server did not become ready:\n"
        + log_path.read_text(encoding="utf-8", errors="replace")
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="auro-dashboard-e2e-") as temp:
        runtime = Path(temp)
        tasks_dir = runtime / "tasks"
        data_dir = runtime / "data"
        sessions_dir = runtime / "sessions"
        screenshots_dir = ROOT / "screenshots"
        tasks_dir.mkdir()
        data_dir.mkdir()
        sessions_dir.mkdir()
        screenshots_dir.mkdir(exist_ok=True)

        shutil.copy2(
            ROOT / "app" / "tasks" / "demo_form.yaml",
            tasks_dir / "demo_form.yaml",
        )

        env = os.environ.copy()
        env.update(
            {
                "DATABASE_PATH": str(data_dir / "automation.db"),
                "TASKS_DIR": str(tasks_dir),
                "DATA_DIR": str(data_dir),
                "SCREENSHOTS_DIR": str(screenshots_dir),
                "SESSIONS_DIR": str(sessions_dir),
                "AUTOMATION_HEADLESS": "true",
            }
        )
        for key in (
            "AUTOMATION_TIMEOUT_MS",
            "AUTOMATION_DELAY_MIN_MS",
            "AUTOMATION_DELAY_MAX_MS",
            "AUTOMATION_RETRY",
        ):
            env.pop(key, None)

        port = free_port()
        base_url = f"http://127.0.0.1:{port}"
        server_log = runtime / "uvicorn.log"

        with server_log.open("w", encoding="utf-8") as log_file:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

            try:
                wait_for_server(f"{base_url}/health", server, server_log)

                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        channel="chrome",
                        headless=True,
                    )
                    page = browser.new_page()
                    page.set_default_timeout(BASE_TIMEOUT_MS)

                    # Dashboard navigation and CSV upload.
                    page.goto(base_url, wait_until="networkidle")
                    assert page.locator("h1").inner_text().strip() == "Automation dashboard"
                    assert page.locator('a.task-name[href="/task/demo_form"]').count() == 1

                    page.locator("#input-file").set_input_files(
                        {
                            "name": "ui_contacts.csv",
                            "mimeType": "text/csv",
                            "buffer": b"first_name,email\nAmina,amina@example.com\n",
                        }
                    )
                    page.locator("#upload-form button[type='submit']").click()
                    page.locator("#upload-result").get_by_text(
                        "Uploaded", exact=False
                    ).wait_for()
                    assert page.locator(
                        'select[name="input_filename"] option'
                    ).count() >= 2

                    # Save settings through the actual settings form.
                    page.goto(f"{base_url}/settings", wait_until="networkidle")
                    page.locator("#headless").select_option("true")
                    page.locator("#delay_min_ms").fill("250")
                    page.locator("#delay_max_ms").fill("750")
                    page.locator("#retry").fill("1")
                    page.locator("#timeout_ms").fill("45000")
                    page.locator(".settings-form button[type='submit']").click()
                    page.wait_for_url("**/settings?saved=1")
                    assert page.get_by_text(
                        "Settings saved successfully", exact=False
                    ).count() or page.locator(".success-banner").count()

                    # Create a task from the Dashboard editor.
                    stop_task_yaml = (
                        'name: stop_ui\n'
                        'description: "UI cancellation smoke test"\n'
                        'headless: true\n'
                        'timeout_ms: 60000\n'
                        'retry: 0\n'
                        'delay:\n'
                        '  min_ms: 0\n'
                        '  max_ms: 0\n'
                        'steps:\n'
                        '  - action: goto\n'
                        '    url: "https://www.selenium.dev/selenium/web/web-form.html"\n'
                        '  - action: wait_for\n'
                        '    selector: "#auro-never-exists"\n'
                        '    state: visible\n'
                    )
                    page.goto(base_url, wait_until="networkidle")
                    page.locator("#new-task-name").fill("stop_ui")
                    page.locator("#new-task-yaml").fill(stop_task_yaml)
                    page.locator(
                        ".task-create-form button[type='submit']"
                    ).click()
                    page.wait_for_url("**/task/stop_ui")

                    # Run the real demo and verify live status, logs and gallery.
                    page.goto(f"{base_url}/task/demo_form", wait_until="networkidle")
                    page.locator(
                        "[data-detail-run-form] button[type='submit']"
                    ).click()

                    page.wait_for_function(
                        """() => {
                            const badges = document.querySelectorAll(
                                '[data-run-card] [data-run-status-badge]'
                            );
                            const last = badges[badges.length - 1];
                            return last && last.textContent.trim().toLowerCase() === 'completed';
                        }""",
                        timeout=90_000,
                    )

                    completed_card = page.locator("[data-run-card]").last
                    completed_card.locator(
                        "[data-run-logs] .log-entry"
                    ).first.wait_for()
                    completed_card.locator(
                        "[data-run-screenshots] a.screenshot-thumb img"
                    ).first.wait_for()
                    page.wait_for_function(
                        """() => {
                            const image = document.querySelector(
                                '[data-run-card]:last-of-type [data-run-screenshots] img'
                            );
                            return image && image.complete && image.naturalWidth > 0;
                        }""",
                        timeout=15_000,
                    )

                    # Start the intentionally waiting task and stop it from the UI.
                    page.goto(f"{base_url}/task/stop_ui", wait_until="networkidle")
                    page.locator(
                        "[data-detail-run-form] button[type='submit']"
                    ).click()
                    stop_button = page.locator("[data-stop-run]")
                    stop_button.wait_for(state="visible")
                    page.wait_for_function(
                        """() => {
                            const button = document.querySelector('[data-stop-run]');
                            return button && !button.disabled;
                        }""",
                        timeout=10_000,
                    )
                    stop_button.click()

                    page.wait_for_function(
                        """() => {
                            const badges = document.querySelectorAll(
                                '[data-run-card] [data-run-status-badge]'
                            );
                            const last = badges[badges.length - 1];
                            return last && last.textContent.trim().toLowerCase() === 'cancelled';
                        }""",
                        timeout=30_000,
                    )

                    cancelled_card = page.locator("[data-run-card]").last
                    assert cancelled_card.locator(
                        "[data-run-logs] .log-entry"
                    ).count() >= 1

                    browser.close()

                print(
                    "AURO dashboard browser E2E passed: dashboard, CSV upload, "
                    "settings, task creation, run status, logs, screenshot gallery, "
                    "and Stop."
                )

            except Exception:
                print(
                    "AURO dashboard browser E2E failed. Server log follows:\n"
                    + server_log.read_text(encoding="utf-8", errors="replace")
                )
                raise
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


if __name__ == "__main__":
    main()
