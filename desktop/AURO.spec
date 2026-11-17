# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH).resolve().parent.parent
BROWSER_PATH = Path(os.environ.get("AURO_BUILD_BROWSERS_PATH", ""))

if not BROWSER_PATH.is_dir():
    raise RuntimeError(
        "AURO_BUILD_BROWSERS_PATH must point to the installed Playwright browsers."
    )

datas = []
binaries = []
hiddenimports = []

# Qt WebEngine, the Playwright Node driver, and Uvicorn load resources dynamically.
for package in ("PySide6", "playwright", "uvicorn"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hidden)

datas.extend(
    [
        (str(ROOT / "app" / "templates"), "app/templates"),
        (str(ROOT / "app" / "static"), "app/static"),
        (str(ROOT / "app" / "tasks"), "app/tasks"),
        (str(ROOT / "desktop" / "assets"), "desktop/assets"),
        (str(BROWSER_PATH), "ms-playwright"),
    ]
)

hiddenimports.extend(
    [
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebChannel",
        "playwright.async_api",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "app.main",
        "app.database",
        "app.runner",
    ]
)

analysis = Analysis(
    [str(ROOT / "desktop" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AURO",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "desktop" / "assets" / "auro.ico"),
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="AURO",
)
