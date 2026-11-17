"""Windows desktop entry point for AURO."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.request import urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from desktop.runtime import configure_runtime  # noqa: E402

RUNTIME = configure_runtime()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        RotatingFileHandler(
            RUNTIME.logs_dir / "auro-desktop.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    ],
    force=True,
)
LOGGER = logging.getLogger("auro.desktop")

# Runtime paths must be configured before importing the FastAPI application.
from app import database  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from desktop.server import LocalServer  # noqa: E402


def _browser_smoke_test(base_url: str) -> None:
    """Launch the bundled Playwright browser and render the local dashboard."""
    from playwright.async_api import async_playwright

    async def run() -> None:
        settings = load_settings()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                channel=settings.browser_channel,
                headless=True,
            )
            try:
                page = await browser.new_page()
                response = await page.goto(
                    base_url,
                    wait_until="domcontentloaded",
                    timeout=25_000,
                )
                if response is None or response.status >= 400:
                    raise RuntimeError("The packaged dashboard did not load.")
                if "AURO" not in await page.title():
                    raise RuntimeError("The packaged dashboard title is incorrect.")
            finally:
                await browser.close()

    asyncio.run(run())


def run_packaged_smoke_test() -> int:
    """Validate the frozen executable, bundled browser, FastAPI app, and assets."""
    if getattr(sys, "frozen", False) and RUNTIME.browser_path is None:
        LOGGER.error("The bundled Playwright Chromium directory is missing.")
        return 2

    server = LocalServer(fastapi_app)
    server.start()
    try:
        server.wait_until_ready()
        with urlopen(server.health_url, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("AURO health endpoint returned an error.")
        _browser_smoke_test(server.base_url)
        LOGGER.info("Packaged desktop smoke test passed.")
        return 0
    except Exception:
        LOGGER.exception("Packaged desktop smoke test failed.")
        return 1
    finally:
        if not server.stop():
            LOGGER.error("The AURO local server did not stop cleanly.")


def _has_active_runs() -> bool:
    """Check recent task runs before allowing the user to close the app."""
    try:
        for task in database.get_tasks():
            recent = database.get_recent_runs(task.name, limit=1)
            if recent and recent[0].status == "running":
                return True
    except Exception:
        LOGGER.exception("Could not inspect active workflow runs.")
    return False


def run_gui() -> int:
    """Start the native Qt window and embedded dashboard."""
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QAction, QDesktopServices, QIcon
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import (
        QApplication,
        QMainWindow,
        QMessageBox,
        QToolBar,
    )

    class AuroWindow(QMainWindow):
        def __init__(self, server: LocalServer) -> None:
            super().__init__()
            self.server = server
            self.started_at = time.monotonic()
            self.loaded = False

            self.setWindowTitle("AURO — Browser Automation")
            self.resize(1440, 920)
            self.setMinimumSize(980, 680)

            icon_path = RUNTIME.bundle_root / "desktop" / "assets" / "auro.ico"
            if icon_path.is_file():
                self.setWindowIcon(QIcon(str(icon_path)))

            toolbar = QToolBar("AURO")
            toolbar.setMovable(False)
            self.addToolBar(toolbar)

            dashboard_action = QAction("Dashboard", self)
            dashboard_action.triggered.connect(self.open_dashboard)
            toolbar.addAction(dashboard_action)

            refresh_action = QAction("Refresh", self)
            refresh_action.triggered.connect(self.refresh_dashboard)
            toolbar.addAction(refresh_action)

            external_action = QAction("Open in Browser", self)
            external_action.triggered.connect(self.open_in_browser)
            toolbar.addAction(external_action)

            self.view = QWebEngineView(self)
            self.setCentralWidget(self.view)
            self.statusBar().showMessage("Starting AURO local engine…")

            self.startup_timer = QTimer(self)
            self.startup_timer.setInterval(300)
            self.startup_timer.timeout.connect(self.check_server)
            self.startup_timer.start()

        def check_server(self) -> None:
            if self.loaded:
                return
            if not self.server.thread.is_alive():
                self.startup_timer.stop()
                QMessageBox.critical(
                    self,
                    "AURO could not start",
                    "The local AURO engine stopped unexpectedly.\n\n"
                    f"Check the log file:\n{RUNTIME.logs_dir / 'auro-desktop.log'}",
                )
                self.close()
                return

            try:
                with urlopen(self.server.health_url, timeout=1) as response:
                    if response.status != 200:
                        return
            except Exception:
                if time.monotonic() - self.started_at > 45:
                    self.startup_timer.stop()
                    QMessageBox.critical(
                        self,
                        "AURO startup timeout",
                        "AURO could not start its local engine within 45 seconds.\n\n"
                        f"Check the log file:\n{RUNTIME.logs_dir / 'auro-desktop.log'}",
                    )
                    self.close()
                return

            self.loaded = True
            self.startup_timer.stop()
            self.view.setUrl(QUrl(self.server.base_url))
            self.statusBar().showMessage(
                "AURO is running locally · 127.0.0.1", 5000
            )

        def open_dashboard(self) -> None:
            self.view.setUrl(QUrl(self.server.base_url))

        def refresh_dashboard(self) -> None:
            self.view.reload()

        def open_in_browser(self) -> None:
            QDesktopServices.openUrl(QUrl(self.server.base_url))

        def closeEvent(self, event) -> None:  # noqa: N802
            if _has_active_runs():
                answer = QMessageBox.question(
                    self,
                    "Workflow is still running",
                    "An automation workflow is currently running.\n\n"
                    "Closing AURO will stop the active workflow. Continue?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return

            self.statusBar().showMessage("Stopping AURO…")
            if not self.server.stop():
                LOGGER.warning("AURO server required forced shutdown.")
            event.accept()

    qt_app = QApplication([sys.argv[0]])
    qt_app.setApplicationName("AURO")
    qt_app.setOrganizationName("AURO")
    qt_app.setQuitOnLastWindowClosed(True)

    server = LocalServer(fastapi_app)
    server.start()

    window = AuroWindow(server)
    window.show()
    return qt_app.exec()


def main() -> int:
    parser = argparse.ArgumentParser(description="AURO Windows Desktop")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    arguments, _ = parser.parse_known_args()
    if arguments.smoke_test:
        return run_packaged_smoke_test()
    try:
        return run_gui()
    except Exception:
        LOGGER.exception("AURO desktop application crashed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
