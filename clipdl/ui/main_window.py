"""Main window: layout of all regions, glass background, fullscreen preview."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from . import theme
from .dropfx import DropOverlay
from .chrome import EmptyView, LoadingView, SessionSwitcher, StatusBar, UrlBar
from .export_panel import ExportPanel
from .player_view import PlayerView
from .progress_panel import DonePanel, ErrorPanel, ProgressPanel
from .trim_track import Ruler, TrimTrack
from .widgets import Card, TimeField, label
from .window_base import GlassWindow

class MainWindow(GlassWindow):
    closing = Signal(object)  # QCloseEvent
    sessionRequested = Signal(str)
    linkDropped = Signal(str)

    def __init__(self):
        super().__init__("Clippr", "PRO")
        self.setMinimumSize(1100, 720)
        self.setAcceptDrops(True)
        self.switcher = SessionSwitcher()
        self.switcher.chosen.connect(self.sessionRequested.emit)
        self.titleBar.add_left(self.switcher)
        self.addActions(self.switcher.shortcut_actions())  # Ctrl+1..5 work anywhere in the window
        self.pages = QStackedWidget()
        self.root.addWidget(self.pages, 1)
        self.clip_page = QWidget()
        root = QVBoxLayout(self.clip_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.pages.addWidget(self.clip_page)
        self.tool_pages: dict[str, QWidget] = {}

        self.url_bar = UrlBar()
        root.addWidget(self.url_bar)

        content = QHBoxLayout()
        self.content_layout = content
        content.setContentsMargins(18, 0, 18, 14)
        content.setSpacing(14)
        root.addLayout(content, 1)

        # ---- left column
        self.left = QStackedWidget()
        self.empty_view = EmptyView()
        self.loading_view = LoadingView()
        self.video_page = QWidget()
        vp = QVBoxLayout(self.video_page)
        vp.setContentsMargins(0, 0, 0, 0)
        vp.setSpacing(14)
        self.player = PlayerView()
        self.player.setMinimumHeight(340)
        vp.addWidget(self.player, 1)
        self.trim_card = Card()
        tc = QVBoxLayout(self.trim_card)
        tc.setContentsMargins(16, 14, 16, 14)
        tc.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label("Trim", "Title"))
        head.addSpacing(6)
        self.trim_hint = label("Drag the handles, type times, or use Set start / Set end while playing", "Faint")
        self.trim_hint.setStyleSheet("font-size:12px;")
        head.addWidget(self.trim_hint, 1)
        self.clip_pill = QLabel()
        self.clip_pill.setObjectName("Pill")
        self.clip_pill.setTextFormat(Qt.RichText)
        head.addWidget(self.clip_pill)
        tc.addLayout(head)
        self.trim = TrimTrack()
        tc.addWidget(self.trim)
        self.ruler = Ruler()
        tc.addWidget(self.ruler)
        times = QHBoxLayout()
        times.setSpacing(12)
        self.start_field = TimeField("Start")
        self.end_field = TimeField("End")
        arrow = QLabel()
        arrow.setPixmap(theme.icon_pixmap("arrow-right", theme.TEXT_4, 18))
        times.addWidget(self.start_field, 0, Qt.AlignBottom)
        times.addWidget(arrow, 0, Qt.AlignBottom)
        times.setAlignment(arrow, Qt.AlignBottom)
        times.addWidget(self.end_field, 0, Qt.AlignBottom)
        times.addStretch(1)
        accepts = QLabel()
        accepts.setTextFormat(Qt.RichText)
        mono = f"font-family:'{theme.FONT_MONO}';color:#C4CEC9"
        accepts.setText(f"<span style='color:{theme.TEXT_3};font-size:12px'>Accepts <span style=\"{mono}\">90</span>, "
                        f"<span style=\"{mono}\">1:30</span> or <span style=\"{mono}\">1:02:30.5</span></span>")
        times.addWidget(accepts, 0, Qt.AlignBottom)
        tc.addLayout(times)
        vp.addWidget(self.trim_card, 0)
        for w in (self.empty_view, self.loading_view, self.video_page):
            self.left.addWidget(w)
        content.addWidget(self.left, 1)

        # ---- right column
        self.side = Card()
        self.side.setFixedWidth(360)
        sv = QVBoxLayout(self.side)
        sv.setContentsMargins(16, 14, 16, 14)
        self.side_stack = QStackedWidget()
        self.export = ExportPanel()
        self.progress = ProgressPanel()
        self.done = DonePanel()
        self.error = ErrorPanel()
        for w in (self.export, self.progress, self.done, self.error):
            self.side_stack.addWidget(w)
        sv.addWidget(self.side_stack)
        content.addWidget(self.side)

        self.bottom_rule = QFrame()
        self.bottom_rule.setFixedHeight(1)
        self.bottom_rule.setStyleSheet("background:rgba(255,255,255,0.06);")
        root.addWidget(self.bottom_rule)
        self.status = StatusBar()
        root.addWidget(self.status)

        self._fullscreen_preview = False
        self.resize(1280, 820)

    # ------------------------------------------------------------ fullscreen preview
    def toggle_fullscreen_preview(self):
        self.set_fullscreen_preview(not self._fullscreen_preview)

    def set_fullscreen_preview(self, on: bool):
        if on == self._fullscreen_preview:
            return
        self._fullscreen_preview = on
        for w in (self.url_bar, self.trim_card, self.side, self.status, self.top_rule, self.bottom_rule):
            w.setVisible(not on)
        self.titleBar.setVisible(not on)
        lay = self.layout()
        if on:
            self._saved_margins = (lay.contentsMargins(), self.content_layout.contentsMargins())
            lay.setContentsMargins(0, 0, 0, 0)
            self.content_layout.setContentsMargins(0, 0, 0, 0)
            self.showFullScreen()
        else:
            lay.setContentsMargins(self._saved_margins[0])
            self.content_layout.setContentsMargins(self._saved_margins[1])
            self.showNormal()

    # ------------------------------------------------------------ drop a link on the Clip Video page
    def _link_in(self, md) -> str | None:
        from ..core.media_info import clean_url
        cands = [u.toString() for u in md.urls() if not u.isLocalFile()] + (md.text() or "").split()
        for c in cands:
            if clean_url(c)[0]:
                return c
        return None

    def _clip_fx(self):
        if not hasattr(self, "clip_fx"):
            self.clip_fx = DropOverlay(self.clip_page)
        return self.clip_fx

    def dragEnterEvent(self, e):  # noqa: N802
        if self.current_session() != "clip":
            e.ignore()
            return
        link = self._link_in(e.mimeData())
        pos = QPointF(self.clip_page.mapFrom(self, e.position().toPoint()))
        if link:
            self._clip_fx().enter(pos, True, "Drop to load the video", link.split("://", 1)[-1][:70], "link")
        else:
            self._clip_fx().enter(pos, False, "Not a video link", "Drop a YouTube, Instagram or X link", "x")
        e.acceptProposedAction()

    def dragMoveEvent(self, e):  # noqa: N802
        if hasattr(self, "clip_fx") and self.clip_fx.isVisible():
            self.clip_fx.move(QPointF(self.clip_page.mapFrom(self, e.position().toPoint())))
            if self.clip_fx._ok:
                e.acceptProposedAction()
                return
        e.ignore()

    def dragLeaveEvent(self, e):  # noqa: N802
        if hasattr(self, "clip_fx"):
            self.clip_fx.leave()

    def dropEvent(self, e):  # noqa: N802
        link = self._link_in(e.mimeData())
        if hasattr(self, "clip_fx"):
            self.clip_fx.drop(QPointF(self.clip_page.mapFrom(self, e.position().toPoint())))
        if link and self.current_session() == "clip":
            e.acceptProposedAction()
            self.linkDropped.emit(link)

    def show_page(self, key: str, page: QWidget | None = None):
        if key == "clip":
            self.pages.setCurrentWidget(self.clip_page)
        else:
            if key not in self.tool_pages and page is not None:
                self.tool_pages[key] = page
                self.pages.addWidget(page)
            self.pages.setCurrentWidget(self.tool_pages[key])
        self.switcher.set_current(key)

    def current_session(self) -> str:
        w = self.pages.currentWidget()
        if w is self.clip_page:
            return "clip"
        return next((k for k, v in self.tool_pages.items() if v is w), "clip")

    def is_fullscreen_preview(self) -> bool:
        return self._fullscreen_preview
