"""
AURO YAML-driven Playwright runner.

This module executes trusted, user-authored YAML workflows using the
installed Google Chrome channel. It supports CSV/TXT input, reusable
browser storage state, screenshots, Playwright traces, retries, and
JSON-formatted logs.

Run from the repository root:
    python -m app.runner app/tasks/demo_form.yaml --headless
    python -m app.runner app/tasks/demo_form.yaml --headless --input data/contacts.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import random
import re
import secrets
import string

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

from app.config import Settings, ensure_runtime_directories, load_settings


# Only actions explicitly implemented below are accepted from YAML.
ALLOWED_ACTIONS = {
    "goto",
    "fill",
    "select",
    "click",
    "wait_for",
    "screenshot",
    "press",
    "check",
    "scroll",
}

TASK_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
TEMPLATE_PATTERN = re.compile(
    r"\{\{\s*(csv\..+?|line|random|now)\s*\}\}"
)


class TaskValidationError(ValueError):
    """Raised when a YAML task does not match the supported schema."""


class JsonFormatter(logging.Formatter):
    """Format each log record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for field in ("run_id", "task_name", "attempt", "step_index"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def get_logger() -> logging.Logger:
    """Create the AURO console logger once, avoiding duplicate handlers."""

    logger = logging.getLogger("auro.runner")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    return logger


LOGGER = get_logger()


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_filename(value: str) -> str:
    """Remove path separators and unsafe characters from a filename part."""

    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned[:100] or "task"


def _require_mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaskValidationError(f"{description} must be a YAML mapping.")
    return value


def _validate_non_negative_int(
    value: Any,
    field_name: str,
    *,
    minimum: int = 0,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TaskValidationError(f"{field_name} must be an integer.")
    if value < minimum:
        raise TaskValidationError(
            f"{field_name} must be at least {minimum}."
        )
    return value


def load_task(task_path: str | Path) -> dict[str, Any]:
    """
    Load and validate a YAML task definition.

    YAML is parsed with safe_load. Unknown step actions and malformed
    selectors are rejected before a browser is launched.
    """

    path = Path(task_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Task YAML file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as task_file:
            raw_task = yaml.safe_load(task_file)
    except yaml.YAMLError as exc:
        raise TaskValidationError(f"Invalid YAML in {path}: {exc}") from exc

    task = _require_mapping(raw_task, "Task definition")

    name = task.get("name")
    if not isinstance(name, str) or not TASK_NAME_PATTERN.fullmatch(name):
        raise TaskValidationError(
            "Task 'name' must be 1-64 characters and contain only "
            "letters, numbers, underscores, or hyphens."
        )

    description = task.get("description", "")
    if not isinstance(description, str):
        raise TaskValidationError("Task 'description' must be a string.")

    if "headless" in task and not isinstance(task["headless"], bool):
        raise TaskValidationError("Task 'headless' must be true or false.")

    if "timeout_ms" in task:
        _validate_non_negative_int(
            task["timeout_ms"], "timeout_ms", minimum=1
        )

    if "retry" in task:
        _validate_non_negative_int(task["retry"], "retry")

    delay = _require_mapping(task.get("delay", {}), "Task 'delay'")
    min_ms = _validate_non_negative_int(
        delay.get("min_ms", 0), "delay.min_ms"
    )
    max_ms = _validate_non_negative_int(
        delay.get("max_ms", min_ms), "delay.max_ms"
    )
    if min_ms > max_ms:
        raise TaskValidationError(
            "delay.min_ms cannot be greater than delay.max_ms."
        )

    storage_state = task.get("storage_state", False)
    if not isinstance(storage_state, (bool, dict)):
        raise TaskValidationError(
            "'storage_state' must be a boolean or a mapping with load/save."
        )
    if isinstance(storage_state, dict):
        for key in ("load", "save"):
            if key in storage_state and not isinstance(storage_state[key], bool):
                raise TaskValidationError(
                    f"storage_state.{key} must be true or false."
                )

    steps = task.get("steps")
    if not isinstance(steps, list) or not steps:
        raise TaskValidationError("'steps' must be a non-empty YAML list.")

    for index, raw_step in enumerate(steps, start=1):
        step = _require_mapping(raw_step, f"Step {index}")
        action = step.get("action")

        if action not in ALLOWED_ACTIONS:
            allowed = ", ".join(sorted(ALLOWED_ACTIONS))
            raise TaskValidationError(
                f"Step {index}: unsupported action {action!r}. "
                f"Allowed actions: {allowed}."
            )

        required_fields: dict[str, tuple[str, ...]] = {
            "goto": ("url",),
            "fill": ("selector", "value"),
            "select": ("selector", "value"),
            "click": ("selector",),
            "wait_for": ("selector",),
            "press": ("selector", "key"),
            "check": ("selector",),
        }

        for field_name in required_fields.get(action, ()):
            if field_name not in step:
                raise TaskValidationError(
                    f"Step {index} ({action}) is missing '{field_name}'."
                )

        if action in {
            "fill", "select", "click", "wait_for",
            "press", "check",
        }:
            selector = step.get("selector")
            if not isinstance(selector, str) or not selector.strip():
                raise TaskValidationError(
                    f"Step {index}: selector must be a non-empty string."
                )

        if action == "goto":
            url = step.get("url")
            if not isinstance(url, str) or not url.strip():
                raise TaskValidationError(
                    f"Step {index}: url must be a non-empty string."
                )

        if action == "press":
            key = step.get("key")
            if not isinstance(key, str) or not key.strip():
                raise TaskValidationError(
                    f"Step {index}: key must be a non-empty string."
                )

        if action == "wait_for":
            state = step.get("state", "visible")
            if state not in {"attached", "detached", "visible", "hidden"}:
                raise TaskValidationError(
                    f"Step {index}: wait_for state is not supported."
                )

        if action == "check" and "checked" in step:
            if not isinstance(step["checked"], bool):
                raise TaskValidationError(
                    f"Step {index}: checked must be true or false."
                )

        if action == "scroll":
            selector = step.get("selector")
            if selector is not None and (
                not isinstance(selector, str) or not selector.strip()
            ):
                raise TaskValidationError(
                    f"Step {index}: scroll selector must be a non-empty string."
                )
            for coordinate in ("x", "y"):
                if coordinate in step and (
                    isinstance(step[coordinate], bool)
                    or not isinstance(step[coordinate], int)
                ):
                    raise TaskValidationError(
                        f"Step {index}: scroll {coordinate} must be an integer."
                    )

    # Store the absolute source path for later task registration and logging.
    task["_source_path"] = str(path)
    return task


def load_input_records(input_path: str | Path | None) -> list[dict[str, str]]:
    """
    Read CSV rows or TXT lines into template contexts.

    CSV:
        Each DictReader row is available as {{csv.column_name}}.

    TXT:
        Each non-empty line is available as {{line}}.
    """

    if input_path is None:
        return [{}]

    path = Path(input_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = path.suffix.lower()

    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as input_file:
            reader = csv.DictReader(input_file)
            if not reader.fieldnames:
                raise ValueError("CSV input must contain a header row.")

            records = [
                {
                    str(key): "" if value is None else str(value)
                    for key, value in row.items()
                    if key is not None
                }
                for row in reader
            ]

        if not records:
            raise ValueError("CSV input contains no data rows.")
        return records

    if suffix == ".txt":
        with path.open("r", encoding="utf-8-sig") as input_file:
            lines = [line.rstrip("\r\n") for line in input_file]
        lines = [line for line in lines if line.strip()]

        if not lines:
            raise ValueError("TXT input contains no non-empty lines.")
        return [{"line": line} for line in lines]

    raise ValueError(
        f"Unsupported input file type {suffix!r}. Use .csv or .txt."
    )


def resolve_templates(value: Any, record: dict[str, str]) -> Any:
    """
    Resolve supported template tokens in strings and nested structures.

    Supported tokens:
        {{csv.column}} - value from the current CSV row
        {{line}}       - current TXT line
        {{random}}     - random 8-character alphanumeric string
        {{now}}        - current UTC ISO timestamp

    Non-string YAML values are preserved.
    """

    if isinstance(value, list):
        return [resolve_templates(item, record) for item in value]

    if isinstance(value, dict):
        return {
            key: resolve_templates(item, record)
            for key, item in value.items()
        }

    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)

        if token.startswith("csv."):
            column = token[4:]
            if column not in record:
                raise ValueError(
                    f"CSV column {column!r} was not found in the current row."
                )
            return record[column]

        if token == "line":
            if "line" not in record:
                raise ValueError(
                    "{{line}} was used but the current input is not a TXT line."
                )
            return record["line"]

        if token == "random":
            alphabet = string.ascii_letters + string.digits
            return "".join(secrets.choice(alphabet) for _ in range(8))

        if token == "now":
            return utc_now()

        # The regular expression should make this branch unreachable.
        raise ValueError(f"Unsupported template token: {token}")

    return TEMPLATE_PATTERN.sub(replace, value)


async def human_delay(min_ms: int, max_ms: int) -> None:
    """Wait for a random configured interval between workflow steps."""

    if max_ms <= 0:
        return

    delay_ms = random.randint(min_ms, max_ms)
    await asyncio.sleep(delay_ms / 1000)


def _storage_options(task: dict[str, Any]) -> tuple[bool, bool]:
    """Return (load, save) options for Playwright storage_state."""

    setting = task.get("storage_state", False)

    if setting is True:
        return True, True
    if setting is False:
        return False, False

    return (
        setting.get("load", True),
        setting.get("save", True),
    )


async def execute_step(
    page: Page,
    step: dict[str, Any],
    *,
    timeout_ms: int,
    screenshot_path: Path,
) -> dict[str, Any] | None:
    """Execute one validated workflow step."""

    action = step["action"]

    if action == "goto":
        await page.goto(
            str(step["url"]),
            wait_until=step.get("wait_until", "domcontentloaded"),
            timeout=timeout_ms,
        )
        return None

    if action == "fill":
        locator = page.locator(step["selector"])
        text_value = "" if step["value"] is None else str(step["value"])

        if step.get("human_like", False):
            # Sequential key presses are useful when testing input events
            # that do not fire when a field is filled in one operation.
            await locator.fill("", timeout=timeout_ms)
            typing_delay = step.get("typing_delay_ms")
            if typing_delay is None:
                typing_delay = random.randint(45, 110)
            _validate_non_negative_int(
                typing_delay, "typing_delay_ms"
            )
            await locator.press_sequentially(
                text_value,
                delay=typing_delay,
                timeout=timeout_ms,
            )
        else:
            await locator.fill(text_value, timeout=timeout_ms)
        return None

    if action == "select":
        await page.locator(step["selector"]).select_option(
            value=str(step["value"]),
            timeout=timeout_ms,
        )
        return None

    if action == "click":
        click_options: dict[str, Any] = {"timeout": timeout_ms}
        if "button" in step:
            click_options["button"] = step["button"]
        if "click_count" in step:
            click_options["click_count"] = int(step["click_count"])
        await page.locator(step["selector"]).click(**click_options)
        return None

    if action == "wait_for":
        await page.locator(step["selector"]).wait_for(
            state=step.get("state", "visible"),
            timeout=timeout_ms,
        )
        return None

    if action == "screenshot":
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(
            path=str(screenshot_path),
            full_page=bool(step.get("full_page", False)),
            animations="disabled",
        )
        return {
            "filename": screenshot_path.name,
            "label": str(step.get("name", "screenshot")),
        }

    if action == "press":
        await page.locator(step["selector"]).press(
            step["key"],
            timeout=timeout_ms,
        )
        return None

    if action == "check":
        locator = page.locator(step["selector"])
        if step.get("checked", True):
            await locator.check(timeout=timeout_ms)
        else:
            await locator.uncheck(timeout=timeout_ms)
        return None

    if action == "scroll":
        selector = step.get("selector")
        if selector:
            await page.locator(selector).scroll_into_view_if_needed(
                timeout=timeout_ms
            )
        else:
            await page.mouse.wheel(
                int(step.get("x", 0)),
                int(step.get("y", 600)),
            )
        return None

    # load_task() validates actions before the browser is started.
    raise TaskValidationError(f"Unsupported action: {action}")


def _record_log(
    run_id: str,
    level: str,
    message: str,
    *,
    task_name: str,
    attempt: int | None = None,
    step_index: int | None = None,
) -> None:
    """Write to JSON console logs and best-effort SQLite run logs."""

    extra: dict[str, Any] = {
        "run_id": run_id,
        "task_name": task_name,
    }
    if attempt is not None:
        extra["attempt"] = attempt
    if step_index is not None:
        extra["step_index"] = step_index

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    LOGGER.log(numeric_level, message, extra=extra)

    # A logging failure should not hide the original browser result.
    try:
        from app.database import log as database_log

        database_log(run_id, level, message)
    except Exception:
        LOGGER.exception(
            "Could not persist a log entry to SQLite.",
            extra=extra,
        )


async def _run_attempt(
    task: dict[str, Any],
    records: list[dict[str, str]],
    *,
    run_id: str,
    attempt: int,
    settings: Settings,
    headless: bool,
    timeout_ms: int,
    delay_min_ms: int,
    delay_max_ms: int,
    screenshots: list[dict[str, str]],
    trace_files: list[str],
) -> None:
    """
    Run all input records in one isolated browser context.

    Each retry starts a fresh browser/context. A failed attempt saves
    a page screenshot (when possible) and a Playwright trace archive.
    """

    task_name = task["name"]
    safe_task_name = safe_filename(task_name)
    session_path = settings.sessions_dir / f"{safe_task_name}.json"
    load_state, save_state = _storage_options(task)

    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    tracing_started = False
    current_global_step = 0
    current_record_index = 0
    attempt_error: Exception | None = None

    try:
        async with async_playwright() as playwright:
            # Use the installed Google Chrome, not Playwright's bundled
            # Chromium. We intentionally do not hide automation signals.
            browser = await playwright.chromium.launch(
                channel=settings.browser_channel,
                headless=headless,
            )

            context_options: dict[str, Any] = {}
            if load_state and session_path.is_file():
                context_options["storage_state"] = str(session_path)
                _record_log(
                    run_id,
                    "INFO",
                    f"Loading saved browser session: {session_path.name}",
                    task_name=task_name,
                    attempt=attempt,
                )

            context = await browser.new_context(**context_options)
            context.set_default_timeout(timeout_ms)

            await context.tracing.start(
                screenshots=True,
                snapshots=True,
                sources=True,
            )
            tracing_started = True

            page = await context.new_page()
            completed_step_count = 0

            for record_index, record in enumerate(records):
                current_record_index = record_index

                for step_index, raw_step in enumerate(task["steps"]):
                    current_global_step = (
                        record_index * len(task["steps"]) + step_index
                    )
                    resolved_step = resolve_templates(raw_step, record)

                    if completed_step_count > 0:
                        await human_delay(delay_min_ms, delay_max_ms)

                    _record_log(
                        run_id,
                        "INFO",
                        f"Record {record_index + 1}/{len(records)}: "
                        f"starting step {step_index + 1} "
                        f"({resolved_step['action']}).",
                        task_name=task_name,
                        attempt=attempt,
                        step_index=current_global_step,
                    )

                    screenshot_path = (
                        settings.screenshots_dir
                        / f"{safe_task_name}_{run_id}_{current_global_step}.png"
                    )

                    screenshot_info = await execute_step(
                        page,
                        resolved_step,
                        timeout_ms=timeout_ms,
                        screenshot_path=screenshot_path,
                    )

                    if screenshot_info is not None:
                        screenshots.append(screenshot_info)

                    completed_step_count += 1

                    _record_log(
                        run_id,
                        "INFO",
                        f"Completed step {step_index + 1}: "
                        f"{resolved_step['action']}.",
                        task_name=task_name,
                        attempt=attempt,
                        step_index=current_global_step,
                    )

            # Save cookies/local storage only after the whole workflow succeeds.
            if save_state:
                settings.sessions_dir.mkdir(parents=True, exist_ok=True)
                await context.storage_state(path=str(session_path))
                _record_log(
                    run_id,
                    "INFO",
                    f"Saved browser session: {session_path.name}",
                    task_name=task_name,
                    attempt=attempt,
                )

            await context.tracing.stop()
            tracing_started = False

    except Exception as exc:
        attempt_error = exc

        _record_log(
            run_id,
            "ERROR",
            f"Attempt {attempt} failed: {type(exc).__name__}: {exc}",
            task_name=task_name,
            attempt=attempt,
            step_index=current_global_step,
        )

        # Capture a screenshot of the current page before closing the context.
        if page is not None:
            failure_path = (
                settings.screenshots_dir
                / f"{safe_task_name}_{run_id}_{current_global_step}_failure.png"
            )
            try:
                failure_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(
                    path=str(failure_path),
                    full_page=True,
                    animations="disabled",
                    timeout=min(timeout_ms, 10000),
                )
                screenshots.append(
                    {
                        "filename": failure_path.name,
                        "label": (
                            f"failure_record_{current_record_index + 1}"
                            f"_attempt_{attempt}"
                        ),
                    }
                )
            except Exception as screenshot_error:
                _record_log(
                    run_id,
                    "WARNING",
                    f"Failure screenshot could not be captured: {screenshot_error}",
                    task_name=task_name,
                    attempt=attempt,
                    step_index=current_global_step,
                )

        # Preserve the Playwright trace for diagnosing this failed attempt.
        if context is not None and tracing_started:
            trace_path = (
                settings.screenshots_dir
                / f"{safe_task_name}_{run_id}_attempt_{attempt}.zip"
            )
            try:
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                await context.tracing.stop(path=str(trace_path))
                trace_files.append(trace_path.name)
            except Exception as trace_error:
                _record_log(
                    run_id,
                    "WARNING",
                    f"Playwright trace could not be saved: {trace_error}",
                    task_name=task_name,
                    attempt=attempt,
                )
            tracing_started = False

    finally:
        if context is not None:
            if tracing_started:
                try:
                    await context.tracing.stop()
                except Exception:
                    pass
            try:
                await context.close()
            except Exception:
                pass

        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass

    if attempt_error is not None:
        raise attempt_error


async def run_task(
    task_path: str | Path,
    *,
    input_path: str | Path | None = None,
    headless: bool | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute a YAML task and return a structured result dictionary.

    If run_id is omitted, this function creates its own SQLite run record.
    FastAPI can create the run first and pass its ID to this function.
    """

    started_at = utc_now()
    task = load_task(task_path)
    settings = load_settings()
    ensure_runtime_directories(settings)

    records = load_input_records(input_path)
    task_name = task["name"]

    # Import inside the function so YAML validation and template utilities
    # can be used independently of database initialization.
    from app import database

    database.init_db()
    database.register_task(task_name, task["_source_path"])

    if run_id is None:
        run_id = database.create_run(
            task_name,
            screenshot_dir=settings.screenshots_dir,
        )
    elif database.get_run(run_id) is None:
        raise ValueError(
            f"Run ID {run_id!r} does not exist in the AURO database."
        )

    run_headless = (
        headless
        if headless is not None
        else task.get("headless", settings.headless)
    )
    timeout_ms = task.get("timeout_ms", settings.timeout_ms)
    retry_count = task.get("retry", settings.retry)

    delay = task.get("delay", {})
    delay_min_ms = delay.get("min_ms", settings.delay_min_ms)
    delay_max_ms = delay.get("max_ms", settings.delay_max_ms)

    screenshots: list[dict[str, str]] = []
    trace_files: list[str] = []
    last_error: str | None = None
    attempts_used = 0
    final_status = "failed"

    _record_log(
        run_id,
        "INFO",
        f"Starting task {task_name!r} with {len(records)} input record(s).",
        task_name=task_name,
    )

    try:
        for attempt in range(1, retry_count + 2):
            attempts_used = attempt
            _record_log(
                run_id,
                "INFO",
                f"Starting attempt {attempt} of {retry_count + 1}.",
                task_name=task_name,
                attempt=attempt,
            )

            try:
                await _run_attempt(
                    task,
                    records,
                    run_id=run_id,
                    attempt=attempt,
                    settings=settings,
                    headless=run_headless,
                    timeout_ms=timeout_ms,
                    delay_min_ms=delay_min_ms,
                    delay_max_ms=delay_max_ms,
                    screenshots=screenshots,
                    trace_files=trace_files,
                )
                final_status = "completed"
                last_error = None
                break

            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"

                if attempt <= retry_count:
                    _record_log(
                        run_id,
                        "WARNING",
                        f"Retrying task after attempt {attempt} failed.",
                        task_name=task_name,
                        attempt=attempt,
                    )
                else:
                    _record_log(
                        run_id,
                        "ERROR",
                        f"Task failed after {attempts_used} attempt(s): {last_error}",
                        task_name=task_name,
                        attempt=attempt,
                    )

        finished_at = utc_now()

        database.finish_run(
            run_id,
            final_status,
            error=last_error,
            screenshot_dir=settings.screenshots_dir,
        )

        result = {
            "run_id": run_id,
            "task_name": task_name,
            "status": final_status,
            "started_at": started_at,
            "finished_at": finished_at,
            "error": last_error,
            "attempts": attempts_used,
            "input_records": len(records),
            "screenshots": screenshots,
            "trace_files": trace_files,
            "screenshot_dir": str(settings.screenshots_dir),
        }

        _record_log(
            run_id,
            "INFO" if final_status == "completed" else "ERROR",
            f"Task finished with status {final_status}.",
            task_name=task_name,
        )
        return result

    except Exception as exc:
        # Keep the database run from remaining stuck in 'running' if
        # an unexpected orchestration/database error occurs.
        finished_at = utc_now()
        last_error = f"{type(exc).__name__}: {exc}"

        try:
            database.finish_run(
                run_id,
                "failed",
                error=last_error,
                screenshot_dir=settings.screenshots_dir,
            )
        except Exception:
            LOGGER.exception(
                "Could not mark the run as failed.",
                extra={"run_id": run_id, "task_name": task_name},
            )

        return {
            "run_id": run_id,
            "task_name": task_name,
            "status": "failed",
            "started_at": started_at,
            "finished_at": finished_at,
            "error": last_error,
            "attempts": attempts_used,
            "input_records": len(records),
            "screenshots": screenshots,
            "trace_files": trace_files,
            "screenshot_dir": str(settings.screenshots_dir),
        }


async def _async_main(args: argparse.Namespace) -> int:
    """Run the CLI task and print its JSON result."""

    result = await run_task(
        args.task_path,
        input_path=args.input,
        headless=True if args.headless else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 1


def main() -> int:
    """Command-line entry point."""

    parser = argparse.ArgumentParser(
        description="Run an AURO YAML browser automation task."
    )
    parser.add_argument(
        "task_path",
        help="Path to a YAML task definition.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome without a visible browser window.",
    )
    parser.add_argument(
        "--input",
        help="Optional .csv or .txt input file for task templates.",
    )

    args = parser.parse_args()

    try:
        return asyncio.run(_async_main(args))
    except (FileNotFoundError, TaskValidationError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
