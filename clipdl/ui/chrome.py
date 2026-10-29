"""Window chrome: title bar, URL bar, status bar, empty + loading views."""
from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import theme
from .widgets import Card, Dot, Shimmer, icon_button, label, repolish

try:
    from qframelesswindow import TitleBar as _LibTitleBar
    HAVE_FRAMELESS = True
except Exception:  # noqa: BLE001
    _LibTitleBar = None
    HAVE_FRAMELESS = False

TITLE_H = 42


def _brand(parent, title: str, badge: str | None, icon_name: str | None) -> QWidget:
    w = QWidget(parent)
    h = QHBoxLayout(w)
    h.setContentsMargins(14, 0, 0, 0)
    h.setSpacing(10)
    logo = QLabel()
    if icon_name:
        logo.setFixedSize(22, 22)
        logo.setAlignment(Qt.AlignCenter)
        logo.setPixmap(theme.icon_pixmap(icon_name, theme.ON_ACCENT, 14, 2.4))
        logo.setStyleSheet(f"background:{theme.ACCENT};border-radius:6px;")
    else:
        logo.setPixmap(theme.app_icon().pixmap(22, 22))
    word = QLabel(title)
    word.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:15px;font-weight:600;letter-spacing:-0.2px;")
    h.addWidget(logo)
    h.addWidget(word)
    if badge:
        h.addWidget(label(badge, "Badge"))
    return w


def title_tool_button(text: str, icon_name: str, tip: str) -> QPushButton:
    b = QPushButton(" " + text)
    b.setObjectName("TitleTool")
    b.setIcon(theme.icon(icon_name, "#C4CEC9", 14))
    b.setIconSize(QSize(14, 14))
    b.setCursor(Qt.PointingHandCursor)
    b.setToolTip(tip)
    return b


def _settings_button() -> QPushButton:
    b = QPushButton()
    b.setObjectName("TitleTool")
    b.setIcon(theme.icon("sliders", "#C4CEC9", 15))
    b.setIconSize(QSize(15, 15))
    b.setFixedWidth(36)
    b.setCursor(Qt.PointingHandCursor)
    b.setToolTip("Appearance & settings")
    b.setAccessibleName("Settings")
    return b


if HAVE_FRAMELESS:
    class TitleBar(_LibTitleBar):
        """Frameless-window title bar: brand on the left, tool buttons + settings, styled window buttons."""

        def __init__(self, parent, title: str = "Clippr", badge: str | None = "PRO",
                     icon_name: str | None = None):
            super().__init__(parent)
            self.setFixedHeight(TITLE_H)
            lay = self.hBoxLayout
            lay.insertWidget(0, _brand(self, title, badge, icon_name), 0, Qt.AlignLeft | Qt.AlignVCenter)
            self.actions = QHBoxLayout()
            self.actions.setSpacing(6)
            self.actions.setContentsMargins(0, 0, 0, 0)
            holder = QWidget(self)
            holder.setLayout(self.actions)
            self.settings_btn = _settings_button()
            self.actions.addWidget(self.settings_btn)
            idx = lay.indexOf(self.minBtn)
            lay.insertWidget(idx, holder, 0, Qt.AlignVCenter)
            lay.insertSpacing(idx + 1, 10)
            for b in (self.minBtn, self.maxBtn, self.closeBtn):
                b.setFixedSize(46, TITLE_H)
                b.setNormalColor(QColor(theme.TEXT_2))
                b.setHoverColor(QColor("#FFFFFF"))
                b.setPressedColor(QColor("#FFFFFF"))
                b.setNormalBackgroundColor(QColor(0, 0, 0, 0))
            for b in (self.minBtn, self.maxBtn):
                b.setHoverBackgroundColor(theme.white(0.06))
                b.setPressedBackgroundColor(theme.white(0.10))
            self.closeBtn.setHoverBackgroundColor(QColor("#C42B1C"))
            self.closeBtn.setPressedBackgroundColor(QColor("#A12317"))
            self.minBtn.setToolTip("Minimize")
            self.maxBtn.setToolTip("Maximize")
            self.closeBtn.setToolTip("Close")
            if sys.platform == "darwin":  # macOS keeps its own traffic lights on the left
                for b in (self.minBtn, self.maxBtn, self.closeBtn):
                    b.hide()
                lay.insertSpacing(0, 74)

        def add_action(self, w: QWidget):
            self.actions.insertWidget(self.actions.count() - 1, w)

        def add_left(self, w: QWidget):
            self.hBoxLayout.insertSpacing(1, 14)
            self.hBoxLayout.insertWidget(2, w, 0, Qt.AlignLeft | Qt.AlignVCenter)
else:
    class TitleBar(QWidget):  # native frame fallback
        def __init__(self, parent, title: str = "Clippr", badge: str | None = "PRO",
                     icon_name: str | None = None):
            super().__init__(parent)
            self.setFixedHeight(TITLE_H)
            h = QHBoxLayout(self)
            h.setContentsMargins(0, 0, 10, 0)
            h.addWidget(_brand(self, title, badge, icon_name))
            h.addStretch(1)
            self.actions = QHBoxLayout()
            self.actions.setSpacing(6)
            h.addLayout(self.actions)
            self.settings_btn = _settings_button()
            self.actions.addWidget(self.settings_btn)

        def add_action(self, w: QWidget):
            self.actions.insertWidget(self.actions.count() - 1, w)

        def add_left(self, w: QWidget):
            self.layout().insertSpacing(1, 14)
            self.layout().insertWidget(2, w)


class SessionSwitcher(QPushButton):
    """Title-bar dropdown that switches the window between sessions (Clip Video, To MP3, Convert…)."""

    chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtGui import QAction, QActionGroup, QKeySequence
        from PySide6.QtWidgets import QMenu
        from .tools.tools import SESSION_INFO, SESSION_ORDER
        self.info = SESSION_INFO
        self.setObjectName("Switcher")
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(14, 14))
        self.setToolTip(f"Switch session ({theme.keys('Ctrl+1')} … {theme.keys(f'Ctrl+{len(SESSION_ORDER)}')})")
        self.menu = QMenu(self)
        self.menu.setObjectName("SessionMenu")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.actions_by_key = {}
        for i, key in enumerate(SESSION_ORDER):
            title, icon_name, desc = SESSION_INFO[key]
            a = QAction(theme.icon(icon_name, "#DCE5E0", 16), f"{title}   ·   {desc}", self)
            a.setCheckable(True)
            a.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            a.setShortcutVisibleInContextMenu(True)
            a.triggered.connect(lambda _=False, k=key: self.chosen.emit(k))
            group.addAction(a)
            self.menu.addAction(a)
            self.actions_by_key[key] = a
        self.clicked.connect(self._open)
        self.set_current("clip")

    def shortcut_actions(self):
        return list(self.actions_by_key.values())

    def _open(self):
        self.menu.setMinimumWidth(max(self.width(), 340))
        self.menu.popup(self.mapToGlobal(self.rect().bottomLeft() + QPoint(0, 6)))

    def set_current(self, key: str):
        title, icon_name, _ = self.info[key]
        self.setText(f" {title}   ▾")
        self.setIcon(theme.icon(icon_name, theme.ACCENT, 14))
        self.actions_by_key[key].setChecked(True)


class UrlBar(QWidget):
    loadRequested = Signal(str)
    pasteRequested = Signal()
    cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 14, 18, 14)
        h.setSpacing(10)
        self.box = QFrame()
        self.box.setObjectName("FieldBox")
        self.box.setAttribute(Qt.WA_StyledBackground, True)
        self.box.setFixedHeight(42)
        b = QHBoxLayout(self.box)
        b.setContentsMargins(12, 0, 6, 0)
        b.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(theme.icon_pixmap("link", theme.TEXT_3, 16))
        self.edit = QLineEdit()
        self.edit.setObjectName("Bare")
        self.edit.setPlaceholderText("Paste a YouTube, Instagram or X link…")
        self.edit.setAccessibleName("Video link")
        self.edit.setStyleSheet("font-size:14px;")
        self.clear_btn = icon_button("x", "Clear link", 28, 14, theme.TEXT_2)
        self.clear_btn.hide()
        self.paste_btn = QPushButton("Paste   " + theme.keys("Ctrl+V").replace("+", " "))
        self.paste_btn.setObjectName("Small")
        self.paste_btn.setCursor(Qt.PointingHandCursor)
        self.paste_btn.setToolTip("Paste a link from the clipboard and load it")
        b.addWidget(ic)
        b.addWidget(self.edit, 1)
        b.addWidget(self.clear_btn)
        b.addWidget(self.paste_btn)
        self.load_btn = QPushButton("Load video")
        self.load_btn.setObjectName("Primary")
        self.load_btn.setFixedHeight(42)
        self.load_btn.setMinimumWidth(116)
        self.load_btn.setCursor(Qt.PointingHandCursor)
        h.addWidget(self.box, 1)
        h.addWidget(self.load_btn)

        self.edit.returnPressed.connect(lambda: self.loadRequested.emit(self.edit.text()))
        self.load_btn.clicked.connect(lambda: self.loadRequested.emit(self.edit.text()))
        self.paste_btn.clicked.connect(self.pasteRequested.emit)
        self.clear_btn.clicked.connect(self._clear)
        self.edit.textChanged.connect(self._on_text)
        from .export_panel import FocusWatcher
        self._fw = FocusWatcher(self.box, self)
        self.edit.installEventFilter(self._fw)

    def _on_text(self, t):
        self.clear_btn.setVisible(bool(t))
        self.set_invalid(False)

    def _clear(self):
        self.edit.clear()
        self.cleared.emit()

    def set_text(self, t: str):
        self.edit.setText(t)

    def text(self) -> str:
        return self.edit.text()

    def set_invalid(self, bad: bool, tip: str = ""):
        self.box.setProperty("invalid", bad)
        self.box.setToolTip(tip)
        repolish(self.box)

    def set_busy(self, busy: bool):
        self.load_btn.setEnabled(not busy)
        self.paste_btn.setEnabled(not busy)
        self.edit.setReadOnly(busy)
        self.clear_btn.setEnabled(not busy)


class StatusBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(8)
        self.dot = Dot(theme.TEXT_4)
        self.text = label("", "Muted")
        self.text.setStyleSheet("font-size:11.5px;")
        self.text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        h.addWidget(self.dot)
        h.addWidget(self.text, 1)
        self.ytdlp_dot = Dot(theme.ACCENT)
        self.ytdlp = label("yt-dlp", "Muted")
        self.ff_dot = Dot(theme.ACCENT)
        self.ff = label("ffmpeg", "Muted")
        for w in (self.ytdlp, self.ff):
            w.setStyleSheet("font-size:11.5px;")
        h.addWidget(self.ytdlp_dot)
        h.addWidget(self.ytdlp)
        h.addSpacing(10)
        h.addWidget(self.ff_dot)
        h.addWidget(self.ff)

    def set_status(self, text: str, color: str = theme.ACCENT, pulse: bool = False):
        self.text.setText(text)
        self.text.setToolTip(text)
        self.dot.set_color(color)
        self.dot.set_pulse(pulse)

    def set_tools(self, ytdlp_version: str | None, ffmpeg_path: str | None, ffmpeg_src: str):
        self.ytdlp_dot.set_color(theme.ACCENT if ytdlp_version else theme.DANGER)
        self.ytdlp.setToolTip(f"yt-dlp {ytdlp_version}" if ytdlp_version else "yt-dlp is not installed")
        self.ff_dot.set_color(theme.ACCENT if ffmpeg_path else theme.DANGER)
        self.ff.setToolTip(f"ffmpeg ({ffmpeg_src}): {ffmpeg_path}" if ffmpeg_path else
                           "ffmpeg not found. Put ffmpeg.exe in the app's bin folder or on PATH.")


class EmptyView(Card):
    pasteRequested = Signal()

    def __init__(self, parent=None):
        super().__init__("EmptyCard", parent)
        v = QVBoxLayout(self)
        v.setSpacing(14)
        v.addStretch(1)
        ic = QLabel()
        ic.setFixedSize(56, 56)
        ic.setAlignment(Qt.AlignCenter)
        ic.setPixmap(theme.icon_pixmap("link", theme.ACCENT, 24))
        ic.setStyleSheet(f"background:{theme.rgba(theme.ACCENT, 0.14)};border-radius:14px;")
        v.addWidget(ic, 0, Qt.AlignHCenter)
        t = label("Paste a video link to begin", "Big")
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        s = label("YouTube, Instagram or X. Watch it right here, mark a start and end, and export exactly that part.", "Muted", wrap=True)
        s.setAlignment(Qt.AlignCenter)
        s.setFixedWidth(420)
        s.setMinimumHeight(44)
        s.setStyleSheet("font-size:14px;")
        v.addWidget(s, 0, Qt.AlignHCenter)
        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton("  Paste link")
        btn.setObjectName("Primary")
        btn.setMinimumHeight(40)
        btn.setMinimumWidth(130)
        btn.setIcon(theme.icon("clipboard", theme.ON_ACCENT, 16, 2.0))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.pasteRequested.emit)
        row.addWidget(btn)
        row.addSpacing(10)
        row.addWidget(label("or press " + theme.keys("Ctrl+V").replace("+", " "), "Faint"))
        row.addStretch(1)
        v.addSpacing(6)
        v.addLayout(row)
        self.error = label("", "ErrorText", wrap=True)
        self.error.setAlignment(Qt.AlignCenter)
        self.error.hide()
        v.addWidget(self.error)
        v.addStretch(1)

    def set_error(self, msg: str | None):
        self.error.setText(msg or "")
        self.error.setVisible(bool(msg))


class LoadingView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        player = QFrame()
        player.setObjectName("PlayerFrame")
        player.setAttribute(Qt.WA_StyledBackground, True)
        player.setFixedHeight(400)
        pv = QVBoxLayout(player)
        pv.addStretch(1)
        t = label("Loading video…", "Muted")
        t.setAlignment(Qt.AlignCenter)
        pv.addWidget(t)
        pv.addWidget(Shimmer(220, 4, 2), 0, Qt.AlignHCenter)
        pv.addStretch(1)
        v.addWidget(player)
        card = Card()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(16, 14, 16, 14)
        cv.setSpacing(14)
        cv.addWidget(Shimmer(120, 14))
        cv.addWidget(Shimmer(None, 84, 8))
        cv.addWidget(Shimmer(340, 40, 8))
        cv.addStretch(1)
        v.addWidget(card, 1)
