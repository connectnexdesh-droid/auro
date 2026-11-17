"""
AURO FastAPI application.

The API owns dashboard pages, task triggering, uploads, run status,
screenshots, and application settings. Browser work is delegated to
the asynchronous Playwright runner in app.runner.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import uuid

from datetime import datetime, timedelta, timezone
from math import ceil

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import database
from app.config import (
    DEFAULT_SETTINGS,
    ensure_runtime_directories,
    load_settings,
)
from app.models import TaskRecord
from app.runner import TaskValidationError, load_task, safe_filename, run_task


LOGGER = logging.getLogger("auro.web")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "app" / "templates"
STATIC_DIR = PROJECT_ROOT / "app" / "static"

# StaticFiles expects its directory to exist at application import time.
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Keep uploaded files small enough for a self-hosted personal dashboard.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".txt"}
TASK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# BackgroundTasks run in the server process. Keep task handles so a user
# can request cancellation while a browser workflow is running.
_ACTIVE_RUN_TASKS: dict[str, asyncio.Task[Any]] = {}
_CANCEL_REQUESTED: set[str] = set()


def synchronize_task_files() -> int:
    """
    Register valid YAML task files from the configured tasks directory.

    Invalid files are logged and skipped so one broken task does not
    prevent the dashboard from starting.
    """

    settings = load_settings()
    settings.tasks_dir.mkdir(parents=True, exist_ok=True)
    registered = 0

    for task_path in sorted(settings.tasks_dir.glob("*.yaml")):
        try:
            task = load_task(task_path)
            database.register_task(task["name"], task_path)
            registered += 1
        except Exception:
            LOGGER.exception("Skipping invalid task file: %s", task_path)

    for task_path in sorted(settings.tasks_dir.glob("*.yml")):
        try:
            task = load_task(task_path)
            database.register_task(task["name"], task_path)
            registered += 1
        except Exception:
            LOGGER.exception("Skipping invalid task file: %s", task_path)

    return registered


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize persistent storage and register tasks at startup."""

    settings = load_settings()
    ensure_runtime_directories(settings)
    database.init_db()
    task_count = synchronize_task_files()
    LOGGER.info("AURO started; registered %d task(s).", task_count)

    yield

    LOGGER.info("AURO application shutting down.")


app = FastAPI(
    title="AURO Browser Automation Panel",
    description="A self-hosted YAML-driven Playwright automation dashboard.",
    version="0.1.0",
    lifespan=lifespan,
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Screenshots are intentionally served from the configured runtime folder.
# Starlette's StaticFiles prevents paths from escaping this directory.
app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)

# This mount also implements GET /screenshots/{filename}.
# The task-specific JSON listing route is defined separately below.
app.mount(
    "/screenshots",
    StaticFiles(directory=str(load_settings().screenshots_dir), check_dir=False),
    name="screenshots",
)


def _task_or_404(name: str) -> TaskRecord:
    """Return a registered task or raise a consistent 404 response."""

    if not TASK_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=404, detail="Task not found.")

    task = database.get_task(name)
    if task is None:
        # Refresh registration in case a YAML task was added while AURO
        # was running, for example by a GitHub Codespaces file edit.
        synchronize_task_files()
        task = database.get_task(name)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    return task


def _elapsed_seconds(
    started_at_value: str,
    finished_at_value: str | None,
    *,
    now: datetime | None = None,
) -> float:
    """Calculate wall-clock run duration, including active runs."""
    current = now or datetime.now(timezone.utc)
    try:
        started_at = datetime.fromisoformat(started_at_value)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        finished_at = (
            datetime.fromisoformat(finished_at_value)
            if finished_at_value
            else current
        )
        if finished_at.tzinfo is None:
            finished_at = finished_at.replace(tzinfo=timezone.utc)

        return max(0.0, (finished_at - started_at).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def _format_duration(seconds: float) -> str:
    """Format elapsed seconds consistently with the dashboard clock."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds_remainder = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds_remainder}s"
    return f"{seconds_remainder}s"


def _save_task_definition(
    name: str,
    yaml_content: str,
    existing_path: str | None = None,
) -> TaskRecord:
    """
    Validate and atomically save a YAML task definition.

    Task files are restricted to the configured tasks directory. The
    runner's schema validator is reused so the dashboard cannot save a
    task that the execution engine would reject.
    """

    if not TASK_NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=422,
            detail="Task name must use letters, numbers, underscores, or hyphens.",
        )

    if not yaml_content.strip():
        raise HTTPException(status_code=422, detail="YAML content cannot be empty.")

    if len(yaml_content.encode("utf-8")) > 128 * 1024:
        raise HTTPException(status_code=413, detail="Task YAML is limited to 128 KB.")

    settings = load_settings()
    settings.tasks_dir.mkdir(parents=True, exist_ok=True)

    if existing_path is not None:
        target = Path(existing_path).resolve()
        if target.parent != settings.tasks_dir.resolve():
            raise HTTPException(
                status_code=400,
                detail="Task file is outside the configured tasks directory.",
            )
        if target.suffix.lower() not in {".yaml", ".yml"}:
            raise HTTPException(status_code=400, detail="Invalid task file extension.")
    else:
        target = (settings.tasks_dir / f"{name}.yaml").resolve()
        if target.exists():
            raise HTTPException(
                status_code=409,
                detail=f"A task named {name!r} already exists.",
            )

    temporary_path = settings.tasks_dir / f".{name}.{uuid.uuid4().hex}.tmp.yaml"

    try:
        temporary_path.write_text(yaml_content, encoding="utf-8")
        validated_task = load_task(temporary_path)

        if validated_task["name"] != name:
            raise HTTPException(
                status_code=422,
                detail="The YAML task name must match the requested task name.",
            )

        temporary_path.replace(target)
        return database.register_task(name, target)

    except HTTPException:
        raise
    except (TaskValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        temporary_path.unlink(missing_ok=True)


@app.post("/tasks/create")
async def create_task(
    name: str = Form(...),
    yaml_content: str = Form(...),
):
    """Create a new YAML task from the dashboard task editor."""

    if database.get_task(name) is not None:
        raise HTTPException(status_code=409, detail="Task already exists.")

    task = _save_task_definition(name, yaml_content)
    return RedirectResponse(url=f"/task/{task.name}", status_code=303)


@app.post("/task/{name}/edit")
async def edit_task(
    name: str,
    yaml_content: str = Form(...),
):
    """Validate and replace an existing task's YAML definition."""

    task = _task_or_404(name)
    _save_task_definition(name, yaml_content, existing_path=task.path)
    return RedirectResponse(url=f"/task/{name}", status_code=303)


def _uploaded_input_path(filename: str) -> Path:
    """Resolve an uploaded data filename without allowing path traversal."""

    settings = load_settings()
    candidate_name = Path(filename.replace("\\", "/")).name

    if candidate_name != filename or candidate_name in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid input filename.")

    candidate = (settings.data_dir / candidate_name).resolve()

    if candidate.parent != settings.data_dir.resolve():
        raise HTTPException(status_code=400, detail="Invalid input file path.")

    if candidate.suffix.lower() not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only CSV and TXT input files are supported.",
        )

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Uploaded input file not found.")

    return candidate


async def _execute_background_run(
    task_path: str,
    run_id: str,
    input_path: str | None = None,
) -> None:
    """
    Execute a previously-created run record after the HTTP response.

    run_task writes the final result to SQLite. This wrapper also handles
    failures that happen before the runner can initialize its own database
    lifecycle, such as malformed YAML or a missing task file.
    """

    # A stop request can arrive after the HTTP response but before Starlette
    # starts this BackgroundTask. Honor that request before opening Chrome.
    if run_id in _CANCEL_REQUESTED:
        _CANCEL_REQUESTED.discard(run_id)
        database.finish_run(run_id, "cancelled", error="Stopped before execution.")
        database.log(run_id, "WARNING", "Run cancelled before browser launch.")
        return

    # Keep the Playwright work in its own asyncio task. Cancelling this child
    # task must not cancel Starlette's ASGI request/background-response task.
    execution_task = asyncio.create_task(
        run_task(
            task_path,
            input_path=input_path,
            run_id=run_id,
        ),
        name=f"auro-run-{run_id}",
    )
    _ACTIVE_RUN_TASKS[run_id] = execution_task

    try:
        result = await execution_task

        if result.get("status") != "completed":
            LOGGER.error(
                "Background run %s finished with status %s: %s",
                run_id,
                result.get("status"),
                result.get("error"),
            )

    except asyncio.CancelledError:
        # Cancelling the asyncio task unwinds the runner's finally blocks,
        # which close the Playwright context and Chrome process.
        try:
            database.finish_run(
                run_id,
                "cancelled",
                error="Stopped by the user.",
            )
            database.log(run_id, "WARNING", "Run stopped by the user.")
        except Exception:
            LOGGER.exception("Could not persist cancellation for run %s.", run_id)
        return

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        LOGGER.exception("Background run %s crashed.", run_id)

        try:
            database.finish_run(run_id, "failed", error=error)
            database.log(run_id, "ERROR", error)
        except Exception:
            LOGGER.exception(
                "Could not persist background failure for run %s.",
                run_id,
            )

    finally:
        _ACTIVE_RUN_TASKS.pop(run_id, None)
        _CANCEL_REQUESTED.discard(run_id)


@app.get("/")
async def dashboard(request: Request):
    """Render the dashboard with registered tasks and their last status."""

    task_records = database.get_tasks()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "tasks": task_records,
            "uploaded_files": _list_uploaded_files(),
            "page_title": "Dashboard",
        },
    )


@app.get("/task/{name}")
async def task_detail(request: Request, name: str):
    """Render one task's metadata, recent run history, logs, and screenshots."""

    task = _task_or_404(name)
    runs = database.get_recent_runs(name, limit=20)

    logs_by_run: dict[str, list[Any]] = {}
    screenshots_by_run: dict[str, list[dict[str, str]]] = {}
    steps_by_run: dict[str, list[dict[str, object]]] = {}
    progress_by_run: dict[str, dict[str, object]] = {}
    now = datetime.now(timezone.utc)
    elapsed_display_by_run = {
        run.id: _format_duration(
            _elapsed_seconds(run.started_at, run.finished_at, now=now)
        )
        for run in runs
    }

    for run in runs:
        logs_by_run[run.id] = database.get_run_logs(run.id, limit=200)
        screenshots_by_run[run.id] = _list_run_screenshots(name, run.id)
        steps_by_run[run.id] = database.get_run_steps(run.id, limit=2000)
        progress_by_run[run.id] = database.get_run_progress(run.id) or {}

    return templates.TemplateResponse(
        request=request,
        name="task_detail.html",
        context={
            "task": task,
            "task_yaml": Path(task.path).read_text(encoding="utf-8")
            if Path(task.path).is_file()
            else "",
            "uploaded_files": _list_uploaded_files(),
            "runs": runs,
            "logs_by_run": logs_by_run,
            "screenshots_by_run": screenshots_by_run,
            "steps_by_run": steps_by_run,
            "progress_by_run": progress_by_run,
            "elapsed_display_by_run": elapsed_display_by_run,
            "page_title": f"Task: {name}",
        },
    )


def _list_uploaded_files() -> list[str]:
    """Return safe names of uploaded CSV/TXT files for the dashboard."""

    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return sorted(
        path.name
        for path in settings.data_dir.iterdir()
        if path.is_file() and path.suffix.lower() in ALLOWED_UPLOAD_EXTENSIONS
    )


def _list_run_screenshots(
    task_name: str,
    run_id: str,
) -> list[dict[str, str]]:
    """Find PNG screenshots created for a task run."""

    settings = load_settings()
    prefix = f"{safe_filename(task_name)}_{safe_filename(run_id)}_"
    found: list[dict[str, str]] = []

    if not settings.screenshots_dir.is_dir():
        return found

    for image_path in sorted(settings.screenshots_dir.glob(f"{prefix}*.png")):
        if image_path.is_file():
            found.append(
                {
                    "filename": image_path.name,
                    "url": f"/screenshots/{image_path.name}",
                }
            )

    return found


@app.post("/task/{name}/run")
async def trigger_task_run(
    name: str,
    background_tasks: BackgroundTasks,
    input_filename: str | None = Form(default=None),
):
    """
    Create a run record and schedule browser execution in the background.

    Optionally pass input_filename to use a previously uploaded CSV/TXT file.
    """

    task = _task_or_404(name)
    task_path = Path(task.path)

    if not task_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Task YAML file is missing: {task.path}",
        )

    input_path: Path | None = None
    if input_filename:
        input_path = _uploaded_input_path(input_filename)

    settings = load_settings()
    run_id = database.create_run(
        name,
        screenshot_dir=settings.screenshots_dir,
    )
    database.log(run_id, "INFO", f"Run queued for task {name}.")

    background_tasks.add_task(
        _execute_background_run,
        str(task_path),
        run_id,
        str(input_path) if input_path else None,
    )

    return JSONResponse(
        status_code=202,
        content={
            "run_id": run_id,
            "task_name": name,
            "status": "running",
            "message": "Automation run queued.",
        },
    )


@app.get("/task/{name}/status/{run_id}")
async def task_run_status(name: str, run_id: str):
    """Return JSON status for frontend polling."""

    _task_or_404(name)
    run = database.get_run(run_id)

    if run is None or run.task_name != name:
        raise HTTPException(status_code=404, detail="Run not found.")

    progress = database.get_run_progress(run_id) or {}
    total_steps = int(progress.get("total_steps", 0))
    completed_steps = int(progress.get("completed_steps", 0))
    now = datetime.now(timezone.utc)

    elapsed_seconds = _elapsed_seconds(
        run.started_at,
        run.finished_at,
        now=now,
    )

    timeline = database.get_run_steps(run_id, limit=2000)
    current_attempt = int(progress.get("attempt", 1))
    duration_samples = [
        int(step["duration_ms"])
        for step in timeline
        if int(step.get("attempt", 1)) == current_attempt
        and step.get("status") == "completed"
        and step.get("duration_ms") is not None
    ]

    # At the start of a retry there may not be completed actions in the
    # current attempt yet. Use the most recent earlier attempt with samples.
    if not duration_samples:
        completed_attempts = [
            int(step.get("attempt", 1))
            for step in timeline
            if step.get("status") == "completed"
            and step.get("duration_ms") is not None
        ]
        if completed_attempts:
            latest_completed_attempt = max(completed_attempts)
            duration_samples = [
                int(step["duration_ms"])
                for step in timeline
                if int(step.get("attempt", 1)) == latest_completed_attempt
                and step.get("status") == "completed"
                and step.get("duration_ms") is not None
            ]

    estimated_remaining_seconds: int | None = None
    expected_finish_at: str | None = None
    if run.status == "running" and total_steps > 0 and duration_samples:
        remaining_steps = max(0, total_steps - completed_steps)
        average_step_ms = sum(duration_samples) / len(duration_samples)
        estimated_remaining_seconds = max(
            0,
            int(ceil(average_step_ms * remaining_steps / 1000)),
        )
        expected_finish_at = (
            now + timedelta(seconds=estimated_remaining_seconds)
        ).isoformat(timespec="seconds")

    progress_percent = (
        100
        if run.status in {"completed", "success"}
        else min(100, int(round(completed_steps / total_steps * 100)))
        if total_steps > 0
        else 0
    )

    return {
        "id": run.id,
        "task_name": run.task_name,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "total_steps": total_steps,
        "completed_steps": completed_steps,
        "current_step": int(progress.get("current_step", 0)),
        "current_action": (
            str(progress.get("current_action") or "Preparing workflow")
            if run.status == "running"
            else run.status.title()
        ),
        "record_index": int(progress.get("record_index", 0)),
        "total_records": int(progress.get("total_records", 0)),
        "attempt": int(progress.get("attempt", 1)),
        "progress_percent": progress_percent,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "estimated_remaining_seconds": estimated_remaining_seconds,
        "expected_finish_at": expected_finish_at,
        "timeline": timeline,
    }


@app.get("/task/{name}/logs/{run_id}")
async def task_run_logs(name: str, run_id: str):
    """Return recent log entries for live dashboard updates."""

    _task_or_404(name)
    run = database.get_run(run_id)

    if run is None or run.task_name != name:
        raise HTTPException(status_code=404, detail="Run not found.")

    return {
        "run_id": run_id,
        "logs": [
            {
                "id": entry.id,
                "level": entry.level,
                "message": entry.message,
                "created_at": entry.created_at,
            }
            for entry in database.get_run_logs(run_id, limit=500)
        ],
    }


@app.post("/task/{name}/stop/{run_id}")
async def stop_task_run(name: str, run_id: str):
    """Request cancellation of a running browser workflow."""

    _task_or_404(name)
    run = database.get_run(run_id)

    if run is None or run.task_name != name:
        raise HTTPException(status_code=404, detail="Run not found.")

    if run.status != "running":
        return {
            "run_id": run_id,
            "status": run.status,
            "message": "This run is no longer running.",
        }

    active_task = _ACTIVE_RUN_TASKS.get(run_id)
    if active_task is not None and not active_task.done():
        active_task.cancel()
    else:
        # The queued BackgroundTask may not have started yet.
        _CANCEL_REQUESTED.add(run_id)

    database.log(run_id, "WARNING", "Stop requested from dashboard.")
    return JSONResponse(
        status_code=202,
        content={
            "run_id": run_id,
            "status": "cancelling",
            "message": "Stop request received.",
        },
    )


@app.get("/task/{name}/screenshots/{run_id}")
async def task_run_screenshots(name: str, run_id: str):
    """List screenshot files associated with one task run."""

    _task_or_404(name)
    run = database.get_run(run_id)

    if run is None or run.task_name != name:
        raise HTTPException(status_code=404, detail="Run not found.")

    screenshots = _list_run_screenshots(name, run_id)
    return {
        "run_id": run_id,
        "task_name": name,
        "screenshots": screenshots,
    }


@app.post("/upload")
async def upload_input_file(file: UploadFile = File(...)):
    """
    Upload a CSV/TXT file into the configured data directory.

    The filename is replaced with a generated safe name to avoid path
    traversal and accidental overwriting of an existing upload.
    """

    original_name = (file.filename or "").replace("\\", "/").split("/")[-1]
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only .csv and .txt files can be uploaded.",
        )

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()

    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The file is too large. Maximum upload size is 10 MB.",
        )

    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="The file must be UTF-8 encoded.",
        ) from exc

    if extension == ".csv":
        try:
            reader = csv.reader(io.StringIO(decoded))
            header = next(reader, None)
        except csv.Error as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid CSV file: {exc}",
            ) from exc

        if not header or not any(column.strip() for column in header):
            raise HTTPException(
                status_code=400,
                detail="CSV file must contain a header row.",
            )

    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = safe_filename(Path(original_name).stem)[:60]
    stored_name = f"{safe_stem}_{uuid.uuid4().hex[:8]}{extension}"
    destination = settings.data_dir / stored_name
    destination.write_bytes(content)

    return JSONResponse(
        status_code=201,
        content={
            "filename": stored_name,
            "original_filename": original_name,
            "size_bytes": len(content),
            "message": "Input file uploaded successfully.",
        },
    )


@app.get("/settings")
async def settings_page(request: Request):
    """Render the application settings form."""

    values = {
        key: database.get_setting(key) or default
        for key, default in DEFAULT_SETTINGS.items()
    }

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "settings": values,
            "saved": request.query_params.get("saved") == "1",
            "page_title": "Settings",
        },
    )


@app.post("/settings")
async def update_settings(
    headless: str = Form(...),
    delay_min_ms: int = Form(...),
    delay_max_ms: int = Form(...),
    retry: int = Form(...),
    timeout_ms: int = Form(30000),
):
    """Validate and save dashboard settings to SQLite."""

    normalized_headless = headless.strip().lower()
    if normalized_headless not in {"true", "false"}:
        raise HTTPException(
            status_code=422,
            detail="Headless must be true or false.",
        )

    if delay_min_ms < 0 or delay_max_ms < 0:
        raise HTTPException(
            status_code=422,
            detail="Delay values cannot be negative.",
        )

    if delay_min_ms > delay_max_ms:
        raise HTTPException(
            status_code=422,
            detail="Minimum delay cannot exceed maximum delay.",
        )

    if retry < 0 or retry > 10:
        raise HTTPException(
            status_code=422,
            detail="Retry must be between 0 and 10.",
        )

    if timeout_ms < 1000 or timeout_ms > 120000:
        raise HTTPException(
            status_code=422,
            detail="Timeout must be between 1000 and 120000 milliseconds.",
        )

    database.set_setting("headless", normalized_headless)
    database.set_setting("delay_min_ms", str(delay_min_ms))
    database.set_setting("delay_max_ms", str(delay_max_ms))
    database.set_setting("retry", str(retry))
    database.set_setting("timeout_ms", str(timeout_ms))

    return RedirectResponse(url="/settings?saved=1", status_code=303)


@app.get("/health")
async def health_check():
    """Simple health endpoint for local checks and container probes."""

    return {"status": "ok", "service": "auro"}
