"""Start the QML front end:  python run.py --qml   (the default now; --classic starts the old widget UI)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from ..core import paths, settings
from .backend import QmlBackend
from .desktop_blur import DesktopBlur, SnapshotProvider
from .tools_backend import ToolsBackend

QML_DIR = Path(__file__).resolve().parent / "qml"


def run(app, argv: list[str]) -> int:
    from ..ui import glass, theme

    theme.load_fonts()
    cfg = settings.AppSettings() if "--reset-settings" in argv else settings.load()
    if cfg.appearance is None:
        cfg.appearance = glass.default_mode()
    if "--solid" in argv:
        cfg.appearance = "solid"
    if "--clear" in argv:
        cfg.appearance = "clear"
    if cfg.appearance == "solid" and "--solid" not in argv:
        pass  # whatever the user saved

    icon = paths.assets_dir() / "app.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    backend = QmlBackend(cfg)
    tools = ToolsBackend(cfg, backend.ffmpeg, backend._save_soon)
    tools.toast.connect(backend.toast)
    snap_provider = SnapshotProvider()
    desktop = DesktopBlur(snap_provider)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("desktop", snap_provider)
    engine.addImageProvider("preview", tools.provider)
    engine.addImportPath(str(QML_DIR))
    if getattr(sys, "frozen", False):  # packaged build: Qt's own QML modules sit next to the app
        for base in (Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent):
            for rel in ("PySide6/qml", "_internal/PySide6/qml"):
                if (base / rel).is_dir():
                    engine.addImportPath(str(base / rel))
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("tools", tools)
    engine.rootContext().setContextProperty("desktop", desktop)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        print("Clippr: the QML interface failed to load. Run with --classic for the old window.")
        return 1
    app.aboutToQuit.connect(tools.shutdown)
    app.aboutToQuit.connect(backend.shutdown)
    # keep Python from garbage-collecting these while the app runs
    app._qml_refs = (engine, backend, tools, desktop, snap_provider)  # type: ignore[attr-defined]
    return app.exec()
