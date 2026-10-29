"""Shared window base (glass background + title bar) and the app-wide appearance manager + settings popover."""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QSlider, QVBoxLayout, QWidget

from . import glass, theme
from .chrome import HAVE_FRAMELESS, TITLE_H, TitleBar
from .widgets import Segmented, label

if HAVE_FRAMELESS:
    from qframelesswindow import FramelessWindow as _Base
else:
    _Base = QWidget


class GlassWindow(_Base):
    """Top-level window that paints its own tint so Frosted / Clear modes can show the desktop through it."""

    close_guard = None  # callable(event) -> bool

    def __init__(self, title: str = "Clippr", badge: str | None = "PRO", icon_name: str | None = None):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowIcon(theme.app_icon())
        self.backdrop = "solid"
        self.opacity = 0.45
        if sys.platform == "darwin":
            # per-pixel alpha so Clear / Frosted can show the desktop (Windows uses DWM for this instead)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        if HAVE_FRAMELESS:
            self.setTitleBar(TitleBar(self, title, badge, icon_name))
            if sys.platform == "darwin":  # keep the native traffic lights; our own buttons are hidden
                try:
                    self.setSystemTitleBarButtonVisible(True)
                except Exception:  # noqa: BLE001
                    pass
        else:
            self.titleBar = TitleBar(self, title, badge, icon_name)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, TITLE_H if HAVE_FRAMELESS else 0, 0, 0)
        self.root.setSpacing(0)
        if not HAVE_FRAMELESS:
            self.root.addWidget(self.titleBar)
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet("background:rgba(255,255,255,0.06);")
        self.top_rule = rule
        self.root.addWidget(rule)

    def closeEvent(self, e):  # noqa: N802
        if self.close_guard is not None and not self.close_guard(e):
            e.ignore()
            return
        super().closeEvent(e)

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        r = self.rect()
        if self.backdrop == "solid":
            p.fillRect(r, QColor(theme.WINDOW_SOLID))
            glow = 1.0
        else:
            tr, tg, tb = theme.GLASS_TINT
            p.setCompositionMode(QPainter.CompositionMode_Source)
            p.fillRect(r, QColor(tr, tg, tb, round(255 * self.opacity)))
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            glow = 0.35 + 0.65 * self.opacity
        # soft green light pooling in from two corners
        p.setRenderHint(QPainter.Antialiasing)
        for cx, cy, rad, a in ((0.08, -0.05, 0.75, 0.16), (1.02, 1.05, 0.65, 0.10)):
            g = QRadialGradient(QPointF(r.width() * cx, r.height() * cy), max(r.width(), r.height()) * rad)
            c = QColor(theme.ACCENT)
            c.setAlphaF(a * glow)
            g.setColorAt(0.0, c)
            c2 = QColor(theme.ACCENT)
            c2.setAlphaF(0.0)
            g.setColorAt(1.0, c2)
            p.fillRect(r, QBrush(g))
        if self.backdrop != "solid":
            # hairline edge so the window outline stays visible over any background
            p.setPen(theme.qcolor(theme.ACCENT, 0.22))
            p.drawRect(r.adjusted(0, 0, -1, -1))

    def apply_appearance(self, mode: str, opacity: float) -> str:
        effective = glass.apply(self, mode)
        self.backdrop = effective
        self.opacity = opacity
        self.update()
        self.titleBar.update()
        return effective

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        mgr = AppearanceManager.instance()
        if mgr is not None:
            QTimer.singleShot(0, lambda: mgr.apply_to(self))


class AppearanceManager(QObject):
    """Holds the app-wide look (mode + opacity) and applies it to every registered window."""

    changed = Signal(str, float)
    _inst = None

    def __init__(self, mode: str, opacity: float):
        super().__init__()
        AppearanceManager._inst = self
        self.mode = mode if mode in glass.MODES else "solid"
        self.opacity = opacity
        self.windows: list[GlassWindow] = []
        self.effective = "solid"
        self._qss_key = None
        self._qss_timer = QTimer(self)
        self._qss_timer.setSingleShot(True)
        self._qss_timer.setInterval(90)
        self._qss_timer.timeout.connect(self._restyle)
        self._restyle()

    @classmethod
    def instance(cls):
        return cls._inst

    def register(self, w: GlassWindow):
        if w not in self.windows:
            self.windows.append(w)
            w.destroyed.connect(lambda *_: self.windows.remove(w) if w in self.windows else None)
        if w.isVisible():
            self.apply_to(w)
        w.titleBar.settings_btn.clicked.connect(lambda: self.show_popover(w))

    def apply_to(self, w: GlassWindow):
        self.effective = w.apply_appearance(self.mode, self.opacity)
        self._restyle()

    def _restyle(self):
        """Regenerate the stylesheet (panels thin out with the opacity slider in see-through modes)."""
        op = round(self.opacity, 2) if self.effective != "solid" else 1.0
        key = (self.effective, op)
        if key != self._qss_key:
            self._qss_key = key
            QApplication.instance().setStyleSheet(theme.qss(self.effective, op))

    def set_mode(self, mode: str):
        self.mode = mode
        for w in list(self.windows):
            if w.isVisible():
                self.apply_to(w)
        self.changed.emit(self.mode, self.opacity)

    def set_opacity(self, v: float):
        self.opacity = v
        for w in self.windows:
            w.opacity = v
            w.update()
        self._qss_timer.start()
        self.changed.emit(self.mode, self.opacity)

    def show_popover(self, w: GlassWindow):
        pop = SettingsPopover(self, w)
        btn = w.titleBar.settings_btn
        pos = btn.mapToGlobal(QPoint(btn.width(), btn.height() + 6))
        pop.adjustSize()
        pop.move(pos.x() - pop.width(), pos.y())
        pop.show()


class SettingsPopover(QFrame):
    """Small popup: window look (Solid / Frosted / Clear + opacity) and sign-in cookies for Instagram / X."""

    cookiesChanged = Signal(object)
    cookies_getter = None  # set by the app: () -> str|None
    cookies_setter = None  # set by the app: (str|None) -> None

    def __init__(self, mgr: AppearanceManager, parent_window):
        super().__init__(parent_window, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("Popover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFixedWidth(320)
        self.mgr = mgr
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 16)
        v.setSpacing(10)
        t = label("Window")
        t.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:15px;font-weight:600;")
        v.addWidget(t)
        self.mode = Segmented([("solid", "Solid"), ("frosted", "Frosted"), ("clear", "Clear")], mgr.mode, tall=True)
        supported = glass.supported()
        for m in ("frosted", "clear"):
            self.mode.set_option_enabled(m, supported)
        self.mode.changed.connect(self._on_mode)
        v.addWidget(self.mode)
        self.help = label("", "Faint", wrap=True)
        self.help.setStyleSheet("font-size:12px;")
        v.addWidget(self.help)
        row = QHBoxLayout()
        row.addWidget(label("Opacity", "FieldLabel"))
        row.addStretch(1)
        self.op_lbl = label("", "Muted")
        self.op_lbl.setStyleSheet(f"font-family:'{theme.FONT_MONO}';font-size:12px;")
        row.addWidget(self.op_lbl)
        v.addLayout(row)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(15, 100)
        self.slider.setValue(round(mgr.opacity * 100))
        self.slider.setAccessibleName("Window opacity")
        self.slider.valueChanged.connect(self._on_opacity)
        v.addWidget(self.slider)
        self._sync()

        if SettingsPopover.cookies_getter is not None:
            sep = QFrame()
            sep.setObjectName("Divider")
            sep.setAttribute(Qt.WA_StyledBackground, True)
            v.addSpacing(4)
            v.addWidget(sep)
            v.addSpacing(4)
            t2 = label("Sign-in cookies")
            t2.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:15px;font-weight:600;")
            v.addWidget(t2)
            tip = ("Safari needs Full Disk Access for Clippr (System Settings › Privacy & Security)."
                   if sys.platform == "darwin" else
                   "Firefox works best; Chrome-based browsers may need to be closed first.")
            h = label("Some Instagram and X videos need you to be signed in. Pick the browser you're signed in with. "
                      + tip, "Faint", wrap=True)
            h.setStyleSheet("font-size:12px;")
            v.addWidget(h)
            import sys as _sys
            browsers = ([(None, "Off"), ("safari", "Safari"), ("chrome", "Chrome"), ("firefox", "Firefox")]
                        if _sys.platform == "darwin" else
                        [(None, "Off"), ("firefox", "Firefox"), ("edge", "Edge"), ("chrome", "Chrome")])
            self.cookie = Segmented(browsers,
                                    SettingsPopover.cookies_getter())
            self.cookie.changed.connect(lambda val: SettingsPopover.cookies_setter(val))
            v.addWidget(self.cookie)
        if not supported:
            note = label("See-through modes need Windows 10 / 11 or macOS.", "Faint", wrap=True)
            note.setStyleSheet("font-size:11px;")
            v.addWidget(note)

    def _on_mode(self, m):
        self.mgr.set_mode(m)
        self._sync()

    def _on_opacity(self, val):
        self.mgr.set_opacity(val / 100)
        self._sync()

    def _sync(self):
        m = self.mgr.mode
        self.help.setText({"solid": "An opaque dark window.",
                           "frosted": "The desktop shows through, softly blurred.",
                           "clear": "See straight through the window, like a Terminal with a transparent profile."}[m])
        self.slider.setEnabled(m != "solid")
        self.op_lbl.setText(f"{self.slider.value()}%")
