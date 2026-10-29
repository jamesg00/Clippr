"""Entry point: python run.py  (options: --solid, --clear, --reset-settings, --session <name>)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication


class AppContext(QObject):
    """Shared state for every window: settings, tool paths, appearance, open tool windows."""

    def __init__(self, cfg, settings_path: Path | None = None):
        super().__init__()
        from .core import paths
        from .ui.window_base import AppearanceManager, SettingsPopover
        self.cfg = cfg
        self.settings_path = settings_path
        self.ffmpeg = paths.ffmpeg_path()
        try:
            from yt_dlp.version import __version__ as v
            self.ytdlp_version = v
        except Exception:  # noqa: BLE001
            self.ytdlp_version = None
        self.appearance = AppearanceManager(cfg.appearance or "solid", cfg.opacity)
        self.appearance.changed.connect(self._on_appearance)
        SettingsPopover.cookies_getter = lambda: self.cfg.cookies
        SettingsPopover.cookies_setter = self._set_cookies
        self.tools: dict[str, object] = {}
        self.main = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.save)

    def _on_appearance(self, mode: str, opacity: float):
        self.cfg.appearance = mode
        self.cfg.opacity = opacity
        self.save_soon()

    def _set_cookies(self, browser):
        self.cfg.cookies = browser
        self.save_soon()

    def save_soon(self):
        self._timer.start()

    def save(self):
        from .core import settings
        settings.save(self.cfg, self.settings_path)

    def switch_session(self, key: str):
        """Show a session page in the main window (tool pages are created the first time they're opened)."""
        from .ui.tools.tools import SESSION_ALIASES, TOOL_CLASSES
        key = SESSION_ALIASES.get(key, key)
        win = self.main
        if key != "clip" and key not in self.tools:
            page = TOOL_CLASSES[key](self)
            self.tools[key] = page
            win.show_page(key, page)
        else:
            win.show_page(key)
        from .ui.tools.tools import SESSION_INFO
        win.setWindowTitle("Clippr" if key == "clip" else f"Clippr · {SESSION_INFO[key][0]}")
        self.cfg.tools["_app"] = {"session": key}
        self.save_soon()

    def can_close(self) -> bool:
        return all(p.can_close() for p in self.tools.values())


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if sys.platform == "win32":
        try:  # own taskbar icon instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Clippr.App")
        except Exception:  # noqa: BLE001
            pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName("Clippr")
    app.setOrganizationName("Clippr")

    if "--classic" not in argv:  # the QML front end is the app now; --classic starts the old widget UI
        from .qml_ui.launcher import run as run_qml
        return run_qml(app, argv)

    from .core import settings
    from .ui import glass, theme
    from .ui.main_window import MainWindow
    from .controller import AppController

    theme.load_fonts()
    cfg = settings.AppSettings() if "--reset-settings" in argv else settings.load()
    if cfg.appearance is None:
        cfg.appearance = glass.default_mode()
    if "--solid" in argv:
        cfg.appearance = "solid"
    if "--clear" in argv:
        cfg.appearance = "clear"

    ctx = AppContext(cfg)
    win = MainWindow()
    ctx.main = win
    ctl = AppController(win, cfg)
    ctx.appearance.register(win)
    win.sessionRequested.connect(ctx.switch_session)
    last = (cfg.tools.get("_app") or {}).get("session", "clip")
    from .ui.tools.tools import SESSION_ALIASES, SESSION_INFO
    last = SESSION_ALIASES.get(last, last)
    if last in SESSION_INFO and last != "clip":
        ctx.switch_session(last)

    def guard(e):
        if not ctx.can_close():
            return False
        if not ctl.on_close(e):
            return False
        ctx.save()
        return True

    win.close_guard = guard

    if cfg.window:
        x, y, w, h = cfg.window
        r = QRect(x, y, w, h)
        if QGuiApplication.screenAt(r.center()) is not None:
            win.setGeometry(r)
    else:
        scr = QGuiApplication.primaryScreen().availableGeometry()
        win.resize(min(1280, scr.width() - 40), min(820, scr.height() - 40))
        win.move(scr.center() - win.rect().center())
    win.show()
    if "--session" in argv:
        i = argv.index("--session")
        if i + 1 < len(argv) and argv[i + 1] in SESSION_INFO:
            QTimer.singleShot(0, lambda: ctx.switch_session(argv[i + 1]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
