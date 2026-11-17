"""A loopback-only Uvicorn server controlled by the desktop shell."""
from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request

from typing import Any

import uvicorn


def reserve_local_port() -> int:
    """Ask Windows for an available ephemeral loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class LocalServer:
    """Run the existing FastAPI app in a managed background thread."""

    def __init__(self, application: Any) -> None:
        self.port = reserve_local_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.health_url = f"{self.base_url}/health"

        config = uvicorn.Config(
            application,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            access_log=False,
            log_config=None,
            timeout_graceful_shutdown=10,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run,
            name="auro-local-server",
            daemon=True,
        )

    def start(self) -> None:
        """Start the local web server exactly once."""
        if not self.thread.is_alive():
            self.thread.start()

    def wait_until_ready(self, timeout_seconds: float = 40.0) -> None:
        """Wait until FastAPI responds to its health endpoint."""
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            if not self.thread.is_alive():
                raise RuntimeError(
                    "AURO's local web server stopped before startup completed."
                )
            try:
                with urllib.request.urlopen(self.health_url, timeout=1.5) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError) as exc:
                last_error = exc
                time.sleep(0.25)

        raise TimeoutError(
            f"AURO did not become ready within {timeout_seconds:.0f} seconds. "
            f"Last error: {last_error}"
        )

    def stop(self, timeout_seconds: float = 15.0) -> bool:
        """Request graceful shutdown and bound the time spent waiting."""
        if not self.thread.is_alive():
            return True

        self.server.should_exit = True
        self.thread.join(timeout_seconds)
        if self.thread.is_alive():
            self.server.force_exit = True
            self.thread.join(3.0)
        return not self.thread.is_alive()
