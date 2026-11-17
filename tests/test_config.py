"""Configuration tests for browser selection and desktop packaging."""
from __future__ import annotations

import pytest

from app.config import load_settings


def test_browser_channel_defaults_to_google_chrome(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "automation.db"))
    monkeypatch.delenv("AUTOMATION_BROWSER_CHANNEL", raising=False)
    assert load_settings().browser_channel == "chrome"


def test_browser_channel_can_select_bundled_chromium(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "automation.db"))
    monkeypatch.setenv("AUTOMATION_BROWSER_CHANNEL", "chromium")
    assert load_settings().browser_channel == "chromium"


def test_browser_channel_rejects_unknown_values(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "automation.db"))
    monkeypatch.setenv("AUTOMATION_BROWSER_CHANNEL", "unknown-browser")
    with pytest.raises(ValueError, match="AUTOMATION_BROWSER_CHANNEL"):
        load_settings()
