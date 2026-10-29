"""Shared building blocks for the tool windows: drop zone, queue, save-to picker, choice grid, batch runner."""
from __future__ import annotations

import itertools
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontMetrics, QGuiApplication, QImage
from PySide6.QtWidgets import (QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from ...core import paths
from ...workers.jobs import FuncJob
from .. import theme
from ..chrome import StatusBar
from ..dropfx import DropOverlay
from ..widgets import Card, Divider, FancyProgress, Segmented, Toggle, icon_button, label, repolish

_ids = itertools.count(1)


def mb(n: int | float) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n < 1000:
        return f"{max(n, 0)} B"
    return f"{n / 1000:.0f} KB"


def reveal(path: str):
    """Show the file selected in Explorer / Finder."""
    paths.reveal(path)


class ElidedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, t):  # noqa: N802
        self._full = t
        self._elide()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        fm = QFontMetrics(self.font())
        super().setText(fm.elidedText(self._full, Qt.ElideMiddle, max(20, self.width())))
        self.setToolTip(self._full)


class ChoiceGrid(QWidget):
    """Several Segmented rows (optionally captioned) that share one exclusive selection."""

    changed = Signal(object)

    def __init__(self, rows: list[tuple[str | None, list[tuple[object, str]]]], value=None):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.segs: list[Segmented] = []
        self._value = None
        for caption, opts in rows:
            if caption:
                c = label(caption, "Faint")
                c.setStyleSheet("font-size:11px;")
                v.addWidget(c)
            seg = Segmented(opts, None)
            seg.clear_selection()
            seg.changed.connect(lambda val, s=seg: self._picked(s, val))
            v.addWidget(seg)
            self.segs.append(seg)
        self.set_value(value)

    def _picked(self, seg, val):
        for s in self.segs:
            if s is not seg:
                s.clear_selection()
        if val != self._value:
            self._value = val
            self.changed.emit(val)

    def set_value(self, val):
        self._value = val
        for s in self.segs:
            if val in s.values():
                s.set_value(val)
            else:
                s.clear_selection()

    def value(self):
        return self._value


class SaveTo(QWidget):
    """'Next to the originals' toggle (file tools) + folder field + Browse."""

    changed = Signal()

    def __init__(self, folder: str, next_to_originals: bool | None):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(label("Save to", "FieldLabel"))
        self.toggle = None
        if next_to_originals is not None:
            row = QHBoxLayout()
            self.toggle = Toggle(next_to_originals, 34, 20)
            self.toggle.setAccessibleName("Save next to the originals")
            row.addWidget(self.toggle)
            row.addSpacing(6)
            row.addWidget(label("Next to the originals"))
            row.addStretch(1)
            v.addLayout(row)
            self.toggle.toggled.connect(self._sync)
        self.folder_row = QWidget()
        fr = QHBoxLayout(self.folder_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(8)
        self.edit = QLineEdit(folder)
        self.edit.setAccessibleName("Output folder")
        self.edit.addAction(theme.icon("folder", theme.TEXT_3, 15), QLineEdit.LeadingPosition)
        self.edit.setStyleSheet(f"font-family:'{theme.FONT_MONO}';font-size:12px;")
        self.edit.setCursorPosition(0)
        self.edit.textEdited.connect(lambda _: self.changed.emit())
        b = QPushButton("Browse")
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(38)
        b.clicked.connect(self._browse)
        fr.addWidget(self.edit, 1)
        fr.addWidget(b)
        v.addWidget(self.folder_row)
        self._sync()

    def _sync(self, *_):
        self.folder_row.setVisible(self.toggle is None or not self.toggle.isChecked())
        self.changed.emit()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Save to", self.edit.text() or str(paths.default_download_dir()))
        if d:
            self.edit.setText(os.path.normpath(d))
            self.edit.setCursorPosition(0)
            self.changed.emit()

    def folder(self) -> str | None:
        if self.toggle is not None and self.toggle.isChecked():
            return None
        return self.edit.text().strip() or str(paths.default_download_dir())

    def state(self) -> dict:
        return {"folder": self.edit.text().strip(),
                "next_to": bool(self.toggle.isChecked()) if self.toggle is not None else None}


class DropZone(QFrame):
    browse = Signal()

    def __init__(self, title: str, hint: str, icon_name: str = "upload"):
        super().__init__()
        self.setObjectName("DropZone")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self)
        v.addStretch(1)
        ic = QLabel()
        ic.setFixedSize(56, 56)
        ic.setAlignment(Qt.AlignCenter)
        ic.setPixmap(theme.icon_pixmap(icon_name, theme.ACCENT, 24))
        ic.setStyleSheet(f"background:{theme.rgba(theme.ACCENT, 0.14)};border-radius:14px;")
        v.addWidget(ic, 0, Qt.AlignHCenter)
        v.addSpacing(6)
        t = label(title)
        t.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:19px;font-weight:600;")
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        h = label(hint, "Muted", wrap=True)
        h.setAlignment(Qt.AlignCenter)
        h.setFixedWidth(380)
        v.addWidget(h, 0, Qt.AlignHCenter)
        v.addSpacing(6)
        b = QPushButton("Choose files…")
        b.setObjectName("Pill")
        b.setFixedWidth(160)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(self.browse.emit)
        v.addWidget(b, 0, Qt.AlignHCenter)
        v.addStretch(1)

    def set_hot(self, on: bool):
        self.setProperty("hot", on)
        repolish(self)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.browse.emit()


IMAGE_RESULT_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".ico"}


def image_to_clipboard(path: str) -> bool:
    img = QImage(path)
    if img.isNull():  # HEIC and friends: go through Pillow
        try:
            import io

            from PIL import Image

            from ...core import images  # noqa: F401  (registers HEIF)
            with Image.open(path) as im:
                buf = io.BytesIO()
                im.convert("RGBA").save(buf, "PNG")
            img = QImage.fromData(buf.getvalue(), "PNG")
        except Exception:  # noqa: BLE001
            return False
    if img.isNull():
        return False
    QGuiApplication.clipboard().setImage(img)
    return True


def animate_in(w: QWidget, delay_ms: int = 0, ms: int = 280):
    """Fade a freshly added row in (staggered when several arrive at once)."""
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", w)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.finished.connect(lambda: w.setGraphicsEffect(None))
    QTimer.singleShot(delay_ms, anim.start)
    w._fade_anim = anim


class QueueRow(QFrame):
    removeRequested = Signal(int)
    clicked = Signal(int)

    def __init__(self, item_id: int, name: str, sub: str, icon_name: str):
        super().__init__()
        self.item_id = item_id
        self.result_path: str | None = None
        self.setObjectName("QueueRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)
        ic = QLabel()
        ic.setFixedSize(34, 34)
        ic.setAlignment(Qt.AlignCenter)
        ic.setPixmap(theme.icon_pixmap(icon_name, "#C4CEC9", 16))
        ic.setStyleSheet("background:rgba(255,255,255,0.06);border-radius:9px;")
        top.addWidget(ic)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.name = ElidedLabel(name)
        self.name.setStyleSheet("font-size:13px;font-weight:500;")
        self.sub = ElidedLabel(sub)
        self.sub.setStyleSheet(f"font-size:12px;color:{theme.TEXT_3};")
        texts.addWidget(self.name)
        texts.addWidget(self.sub)
        top.addLayout(texts, 1)
        self.pct = label("")
        self.pct.setStyleSheet(f"font-family:'{theme.FONT_MONO}';font-size:12px;color:{theme.TEXT_2};")
        top.addWidget(self.pct)
        self.show_btn = QPushButton(" Show")
        self.show_btn.setObjectName("Small")
        self.show_btn.setIcon(theme.icon("folder", "#DCE5E0", 13))
        self.show_btn.setCursor(Qt.PointingHandCursor)
        self.show_btn.hide()
        self.show_btn.clicked.connect(lambda: self.result_path and reveal(self.result_path))
        top.addWidget(self.show_btn)
        self.copy_btn = QPushButton(" Copy")
        self.copy_btn.setObjectName("Small")
        self.copy_btn.setIcon(theme.icon("clipboard", "#DCE5E0", 13))
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setToolTip("Copy the picture so you can paste it anywhere")
        self.copy_btn.hide()
        self.copy_btn.clicked.connect(self._copy)
        top.addWidget(self.copy_btn)
        self.remove_btn = icon_button("x", "Remove from the list", 28, 13, theme.TEXT_2)
        self.remove_btn.clicked.connect(lambda: self.removeRequested.emit(self.item_id))
        top.addWidget(self.remove_btn)
        v.addLayout(top)
        self.bar = FancyProgress(4)
        self.bar.hide()
        v.addWidget(self.bar)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.item_id)
        super().mousePressEvent(e)

    def set_selected(self, on: bool):
        if bool(self.property("selected")) != on:
            self.setProperty("selected", on)
            repolish(self)

    def _copy(self):
        if self.result_path and image_to_clipboard(self.result_path):
            self.copy_btn.setText(" Copied")
            QTimer.singleShot(1400, lambda: self.copy_btn.setText(" Copy"))

    def set_running(self):
        self.remove_btn.hide()
        self.bar.show()
        self.bar.set_mode("indeterminate")
        self.sub.setText("Starting…")
        self.sub.setStyleSheet(f"font-size:12px;color:{theme.TEXT_2};")

    def set_progress(self, pct, text):
        if pct is None:
            self.bar.set_mode("indeterminate")
            self.pct.setText("")
        else:
            self.bar.set_mode("normal")
            self.bar.set_value(pct)
            self.pct.setText(f"{int(pct)}%")
        if text:
            self.sub.setText(text)

    def set_done(self, text: str, path: str | None):
        self.bar.hide()
        self.pct.setText("")
        self.result_path = path
        self.sub.setText(text)
        self.sub.setStyleSheet(f"font-size:12px;color:{theme.ACCENT};")
        self.show_btn.setVisible(bool(path))
        self.copy_btn.setVisible(bool(path) and Path(path).suffix.lower() in IMAGE_RESULT_EXT)
        self.remove_btn.show()

    def set_error(self, text: str):
        self.bar.hide()
        self.pct.setText("")
        self.sub.setText(text)
        self.sub.setStyleSheet(f"font-size:12px;color:{theme.DANGER};")
        self.remove_btn.show()

    def set_pending(self, text: str = "Waiting"):
        self.bar.hide()
        self.pct.setText("")
        self.sub.setText(text)
        self.sub.setStyleSheet(f"font-size:12px;color:{theme.TEXT_3};")
        self.remove_btn.show()


class ToolWindow(QWidget):
    """One session page inside the main window (queue on the left, options on the right)."""

    KEY = "tool"
    TITLE = "Tool"
    ICON = "file"
    ACCEPTS: set | None = None  # file extensions accepted, None = any file
    URL_INPUT = False
    URL_SITES = "YouTube, Instagram or X"  # shown in link hints and errors
    AUDIO_LINKS = False  # also take audio-only sites (SoundCloud)
    DROP_TITLE = "Drop files here"
    DROP_HINT = ""
    ROW_ICON = "file"
    START_LABEL = "Start"
    NEXT_TO_ORIGINALS: bool | None = True

    def __init__(self, ctx):
        super().__init__()
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)
        self.ctx = ctx
        self.pool = QThreadPool.globalInstance()
        self.opts = dict(ctx.cfg.tools.get(self.KEY, {}))
        self.items: dict[int, dict] = {}
        self.order: list[int] = []
        self.job: FuncJob | None = None
        self.running = False
        self._stop = False
        self.setAcceptDrops(True)

        body = QHBoxLayout()
        body.setContentsMargins(18, 14, 18, 14)
        body.setSpacing(14)
        self.root.addLayout(body, 1)

        # ---- left: queue
        left = Card()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(12)
        head = QHBoxLayout()
        self.q_title = label("Queue")
        self.q_title.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:16px;font-weight:600;")
        head.addWidget(self.q_title)
        self.q_count = label("", "Faint")
        head.addWidget(self.q_count)
        head.addStretch(1)
        self.clear_btn = QPushButton("Clear finished")
        self.clear_btn.setObjectName("Link")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_finished)
        head.addWidget(self.clear_btn)
        if not self.URL_INPUT:
            paste = QPushButton(" Paste")
            paste.setObjectName("Small")
            paste.setIcon(theme.icon("clipboard", "#DCE5E0", 13))
            paste.setCursor(Qt.PointingHandCursor)
            paste.setToolTip(f"Paste files, a copied picture or an image link ({theme.keys('Ctrl+V')})")
            paste.clicked.connect(self.paste_from_clipboard)
            head.addSpacing(8)
            head.addWidget(paste)
            add = QPushButton(" Add files")
            add.setObjectName("Small")
            add.setIcon(theme.icon("plus", "#DCE5E0", 13))
            add.setCursor(Qt.PointingHandCursor)
            add.clicked.connect(self.browse_files)
            head.addSpacing(8)
            head.addWidget(add)
        lv.addLayout(head)
        if self.URL_INPUT:
            lv.addWidget(self._build_url_row())
        self.stack = QStackedWidget()
        self.drop = DropZone(self.DROP_TITLE, self.DROP_HINT, "link" if self.URL_INPUT else "upload")
        self.drop.browse.connect(self.browse_files if not self.URL_INPUT else self._paste)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.list_layout = QVBoxLayout(inner)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(inner)
        self.stack.addWidget(self.drop)
        self.list_area = self.build_list_area(self.scroll)
        self.stack.addWidget(self.list_area)
        lv.addWidget(self.stack, 1)
        body.addWidget(left, 1)

        # ---- right: options
        right = Card()
        right.setFixedWidth(350)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(16, 14, 16, 14)
        rv.setSpacing(14)
        t = label("Options")
        t.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:16px;font-weight:600;")
        rv.addWidget(t)
        # options scroll if the window is too short for them, instead of being squashed
        opts_host = QWidget()
        ol = QVBoxLayout(opts_host)
        ol.setContentsMargins(0, 0, 6, 0)
        ol.setSpacing(14)
        self.build_options(ol)
        ol.addStretch(1)
        opts_scroll = QScrollArea()
        opts_scroll.setWidgetResizable(True)
        opts_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        opts_scroll.setFrameShape(QFrame.NoFrame)
        opts_scroll.setWidget(opts_host)
        rv.addWidget(opts_scroll, 1)
        rv.addWidget(Divider())
        st = self.opts.get("save", {})
        default_folder = st.get("folder") or str(paths.default_download_dir())
        nxt = st.get("next_to", self.NEXT_TO_ORIGINALS) if self.NEXT_TO_ORIGINALS is not None else None
        self.save_to = SaveTo(default_folder, nxt)
        self.save_to.changed.connect(self.remember)
        rv.addWidget(self.save_to)
        self.summary = label("", "Faint", wrap=True)
        self.summary.setStyleSheet("font-size:12px;")
        rv.addWidget(self.summary)
        self.start_btn = QPushButton("  " + self.START_LABEL)
        self.start_btn.setObjectName("Primary")
        self.start_btn.setProperty("pill", True)
        self.start_btn.setIcon(theme.icon(self.ICON, theme.ON_ACCENT, 16, 2.2))
        self.start_btn.setIconSize(QSize(16, 16))
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self.start)
        rv.addWidget(self.start_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Pill")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.hide()
        rv.addWidget(self.cancel_btn)
        body.addWidget(right)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet("background:rgba(255,255,255,0.06);")
        self.root.addWidget(rule)
        self.status = StatusBar()
        self.status.set_tools(ctx.ytdlp_version, ctx.ffmpeg, paths.ffmpeg_source())
        self.root.addWidget(self.status)
        self.fx = DropOverlay(self)
        self._web_jobs: dict[str, FuncJob] = {}
        self._web_n = 0
        self._added_burst = 0
        self._refresh()

    # ------------------------------------------------------------ to override
    def build_options(self, layout: QVBoxLayout):
        pass

    def options(self) -> dict:
        return {}

    def task(self, item: dict, opts: dict):
        """Return fn(progress, log, cancel) -> result."""
        raise NotImplementedError

    def describe(self, item: dict, result) -> tuple[str, str | None]:
        """(row text, path to reveal)"""
        return "Done", result if isinstance(result, str) else None

    def item_label(self, src: str) -> tuple[str, str]:
        p = Path(src)
        try:
            size = mb(p.stat().st_size)
        except OSError:
            size = ""
        return p.name, size

    def after_batch(self):
        pass

    def row_icon(self, src: str) -> str:
        return self.ROW_ICON

    def build_list_area(self, scroll: QScrollArea) -> QWidget:
        """The page shown once the queue has items (the Resize tool wraps it with its editor)."""
        return scroll

    def select_item(self, iid: int):
        pass

    def takes_images(self) -> bool:
        return self.ACCEPTS is None or ".png" in self.ACCEPTS

    # ------------------------------------------------------------ queue
    def _build_url_row(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        box = QFrame()
        box.setObjectName("FieldBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setFixedHeight(40)
        b = QHBoxLayout(box)
        b.setContentsMargins(12, 0, 6, 0)
        ic = QLabel()
        ic.setPixmap(theme.icon_pixmap("link", theme.TEXT_3, 15))
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("Bare")
        self.url_edit.setPlaceholderText(f"Paste a {self.URL_SITES} link and press Enter")
        self.url_edit.setAccessibleName("Link")
        self.url_edit.returnPressed.connect(self._add_url_text)
        paste = QPushButton("Paste")
        paste.setObjectName("Small")
        paste.setCursor(Qt.PointingHandCursor)
        paste.clicked.connect(self._paste)
        b.addWidget(ic)
        b.addWidget(self.url_edit, 1)
        b.addWidget(paste)
        add = QPushButton("Add")
        add.setObjectName("Primary")
        add.setFixedHeight(40)
        add.setMinimumWidth(76)
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self._add_url_text)
        h.addWidget(box, 1)
        h.addWidget(add)
        self.url_error = label("", "ErrorText")
        self.url_error.hide()
        wrap = QWidget()
        wv = QVBoxLayout(wrap)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(6)
        wv.addWidget(w)
        wv.addWidget(self.url_error)
        return wrap

    def _paste(self):
        from PySide6.QtGui import QGuiApplication
        text = QGuiApplication.clipboard().text() or ""
        self.add_urls(text)

    def _add_url_text(self):
        self.add_urls(self.url_edit.text())

    def clean_link(self, text: str) -> str | None:
        from ...core.media_info import clean_audio_url, clean_url
        return (clean_audio_url if self.AUDIO_LINKS else clean_url)(text)[0]

    def add_urls(self, text: str) -> int:
        from ...core.media_info import SITE_NAMES, site_of
        added, bad = 0, 0
        for part in text.replace(",", " ").split():
            clean = self.clean_link(part)
            if not clean:
                bad += 1
                continue
            if any(it["src"] == clean for it in self.items.values()):
                continue
            site = SITE_NAMES.get(site_of(clean), "")
            self._add_item(clean, clean.split("://", 1)[-1], f"{site} · waiting")
            added += 1
        if hasattr(self, "url_edit"):
            if added:
                self.url_edit.clear()
            sites = self.URL_SITES
            self.url_error.setText("" if not bad else (f"That isn't a {sites} link." if not added else
                                                       f"Skipped {bad} link(s) that aren't {sites}."))
            self.url_error.setVisible(bool(bad))
        return added

    def browse_files(self):
        if self.ACCEPTS:
            pats = " ".join(f"*{e}" for e in sorted(self.ACCEPTS))
            flt = f"Supported files ({pats});;All files (*)"
        else:
            flt = "All files (*)"
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files", self.opts.get("last_dir", str(Path.home())), flt)
        if files:
            self.opts["last_dir"] = str(Path(files[0]).parent)
            self.add_files(files)

    def accepts(self, path: str) -> bool:
        p = Path(path)
        return p.is_file() and (self.ACCEPTS is None or p.suffix.lower() in self.ACCEPTS)

    def add_files(self, files: list[str]) -> int:
        added, skipped = 0, 0
        for f in files:
            if os.path.isdir(f):
                for root, _, names in os.walk(f):
                    for n in names:
                        fp = os.path.join(root, n)
                        if self.accepts(fp):
                            added += self._add_file(fp)
                continue
            if self.accepts(f):
                added += self._add_file(f)
            else:
                skipped += 1
        if skipped:
            self.status.set_status(f"Skipped {skipped} file(s) this tool can't handle.", theme.DANGER)
        return added

    def _add_file(self, f: str) -> int:
        f = os.path.normpath(f)
        if any(it["src"] == f and it["status"] in ("pending", "running") for it in self.items.values()):
            return 0
        name, sub = self.item_label(f)
        self._add_item(f, name, sub)
        return 1

    def _add_item(self, src: str, name: str, sub: str):
        iid = next(_ids)
        row = QueueRow(iid, name, sub, self.row_icon(src))
        row.removeRequested.connect(self.remove_item)
        row.clicked.connect(self.select_item)
        self.items[iid] = {"id": iid, "src": src, "status": "pending", "row": row, "result": None, "sub": sub}
        self.order.append(iid)
        self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        # rows arriving together cascade in
        animate_in(row, min(self._added_burst, 12) * 45)
        self._added_burst += 1
        QTimer.singleShot(0, self._reset_burst)
        self._refresh()
        return iid

    def _reset_burst(self):
        self._added_burst = 0

    def remove_item(self, iid: int):
        it = self.items.get(iid)
        if not it or it["status"] == "running":
            return
        it["row"].deleteLater()
        del self.items[iid]
        self.order.remove(iid)
        self._refresh()

    def clear_finished(self):
        for iid in list(self.order):
            if self.items[iid]["status"] in ("done", "error", "cancelled"):
                self.remove_item(iid)

    def _refresh(self):
        n = len(self.items)
        pending = sum(1 for it in self.items.values() if it["status"] == "pending")
        done = sum(1 for it in self.items.values() if it["status"] == "done")
        self.stack.setCurrentWidget(self.list_area if n else self.drop)
        self.q_count.setText(f"{n} item{'s' if n != 1 else ''}" + (f" · {done} done" if done else "") if n else "")
        self.clear_btn.setVisible(any(it["status"] in ("done", "error", "cancelled") for it in self.items.values()))
        self.start_btn.setEnabled(pending > 0 and not self.running and self.ready())
        label_n = f" ({pending})" if pending > 1 else ""
        self.start_btn.setText("  " + self.START_LABEL + label_n)
        self.update_summary()

    def ready(self) -> bool:
        return True

    def update_summary(self):
        pass

    # ------------------------------------------------------------ drag & drop / paste
    def describe_mime(self, md) -> tuple[bool, str, str, str]:
        """(usable, title, subtitle, icon) for the drop overlay."""
        local = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if local:
            n_ok, n_bad = 0, 0
            for f in local[:400]:
                if os.path.isdir(f):
                    n_ok += 1
                elif self.accepts(f):
                    n_ok += 1
                else:
                    n_bad += 1
            if not n_ok:
                return False, "Can't use " + ("this file" if n_bad == 1 else "these files"), \
                    (self.DROP_HINT or "This tool doesn't handle that type."), "x"
            kind = "folder" if all(os.path.isdir(f) for f in local) else "file"
            title = f"Drop {n_ok} {kind}{'s' if n_ok != 1 else ''}"
            return True, title, (f"{n_bad} will be skipped" if n_bad else "Release to add to the queue"), "upload"
        if self.URL_INPUT:
            text = md.text() or " ".join(u.toString() for u in md.urls())
            n = sum(1 for part in text.replace(",", " ").split() if self.clean_link(part))
            if n:
                return True, f"Drop {n} link{'s' if n != 1 else ''}", self.URL_SITES.replace(", ", " · ").replace(" or ", " · "), "link"
            return False, "Not a supported link", f"Drop a {self.URL_SITES} link", "x"
        if self.takes_images():
            if md.hasImage():
                return True, "Drop picture", "Straight from your browser", "image"
            from ...core import webimage
            if (md.hasHtml() and webimage.img_sources(md.html())) or any(
                    u.scheme() in ("http", "https", "data") for u in md.urls()) or webimage.is_web_url(md.text()):
                return True, "Drop picture", "It will be downloaded from the web", "image"
        return False, "Can't use this", "Drop files from your computer", "x"

    def dragEnterEvent(self, e):  # noqa: N802
        ok, title, sub, ic = self.describe_mime(e.mimeData())
        e.acceptProposedAction()
        self.fx.enter(QPointF(e.position()), ok, title, sub, ic)
        self.drop.set_hot(ok)

    def dragMoveEvent(self, e):  # noqa: N802
        self.fx.move(QPointF(e.position()))
        if self.fx._ok:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):  # noqa: N802
        self.drop.set_hot(False)
        self.fx.leave()

    def dropEvent(self, e):  # noqa: N802
        self.drop.set_hot(False)
        ok = self.fx._ok
        self.fx.drop(QPointF(e.position()))
        if ok:
            e.acceptProposedAction()
            self.ingest_mime(e.mimeData())

    def paste_shortcut(self):
        self.paste_from_clipboard()

    def paste_from_clipboard(self):
        md = QGuiApplication.clipboard().mimeData()
        if md is None or not self.ingest_mime(md, pasted=True):
            if self.takes_images():
                msg = "Nothing to paste. Copy files, a picture or an image link first."
            else:
                msg = f"Nothing to paste. Copy some files first ({theme.keys('Ctrl+C')} in {paths.file_manager()})."
            self.status.set_status(msg, theme.DANGER)

    def ingest_mime(self, md, pasted: bool = False) -> bool:
        """Add whatever the clipboard / drop holds. Returns False when there was nothing usable."""
        from ...core import webimage
        local = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if local:
            self.add_files(local)
            return True
        text = md.text() or ""
        if self.URL_INPUT:
            return bool(self.add_urls(text or " ".join(u.toString() for u in md.urls())))
        if not self.takes_images():
            return False
        # a local path pasted as text
        for line in text.splitlines():
            t = line.strip().strip('"')
            if t and len(t) < 1000 and os.path.isabs(t) and os.path.exists(t):
                self.add_files([t])
                return True
        img = QImage(md.imageData()) if md.hasImage() else None
        if img is not None and img.isNull():
            img = None
        srcs = webimage.img_sources(md.html()) if md.hasHtml() else []
        srcs += [u.toString() for u in md.urls() if u.scheme() in ("http", "https", "data")]
        srcs += [t for t in text.split() if webimage.is_web_url(t) or webimage.is_data_uri(t)]
        seen = []
        for u in srcs:
            if u not in seen:
                seen.append(u)
        if seen:
            self._fetch_web(seen[:20], img)
            return True
        if img is not None:
            self.add_files([self._save_qimage(img)])
            return True
        return False

    def _save_qimage(self, img: QImage) -> str:
        import time as _t

        from ...core import encode, webimage
        dst = encode.unique_path(webimage.pasted_dir(), _t.strftime("Pasted %Y-%m-%d %H.%M.%S"), "png")
        img.save(str(dst), "PNG")
        return str(dst)

    def _fetch_web(self, urls: list[str], fallback: QImage | None):
        """Download pictures in the background, then queue them. The copied bitmap is the fallback."""
        from ...core import webimage
        self._web_n += 1
        token = f"web{self._web_n}"

        def fn(progress, log, cancel):
            # the candidates are usually the same picture (srcset size, src, link): first one that works wins
            errs = []
            for u in urls:
                try:
                    return [webimage.download_image(u, cancel=cancel.is_set)], errs
                except Exception as ex:  # noqa: BLE001
                    if cancel.is_set():
                        raise
                    errs.append(str(ex))
            return [], errs

        job = FuncJob(token, fn)
        job.signals.done.connect(lambda payload, fb=fallback: self._on_web_done(payload, fb))
        job.signals.failed.connect(lambda msg, detail, t=token, fb=fallback: self._on_web_failed(t, msg, fb))
        self._web_jobs[token] = job
        self.status.set_status("Downloading the picture…", theme.ACCENT, True)
        self.pool.start(job)

    def _on_web_done(self, payload, fallback):
        token, (paths_, errs) = payload
        self._web_jobs.pop(token, None)
        if paths_:
            self.add_files(paths_)
            self.status.set_status(f"Added {len(paths_)} picture{'s' if len(paths_) != 1 else ''} from the web "
                                   "(saved in Downloads › Pasted images).", theme.ACCENT)
        else:
            self._on_web_failed(token, errs[0] if errs else "Couldn't download that picture.", fallback)

    def _on_web_failed(self, token, msg, fallback):
        self._web_jobs.pop(token, None)
        if fallback is not None:
            self.add_files([self._save_qimage(fallback)])
            self.status.set_status("Added the copied picture.", theme.ACCENT)
        else:
            self.status.set_status(msg, theme.DANGER)

    # ------------------------------------------------------------ settings
    def remember(self, *_):
        o = self.options()
        o["save"] = self.save_to.state()
        if "last_dir" in self.opts:
            o["last_dir"] = self.opts["last_dir"]
        self.opts.update(o)
        self.ctx.cfg.tools[self.KEY] = dict(self.opts)
        self.ctx.save_soon()
        self._refresh()

    # ------------------------------------------------------------ runner
    def start(self):
        if self.running:
            return
        if self.needs_ffmpeg() and not self.ctx.ffmpeg:
            self.status.set_status("ffmpeg wasn't found. Put ffmpeg.exe in the app's bin folder or on PATH.",
                                   theme.DANGER)
            return
        self.remember()
        self.running = True
        self._stop = False
        self.start_btn.hide()
        self.cancel_btn.show()
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel")
        self._batch_opts = self.options()
        self._batch_opts["folder"] = self.save_to.folder()
        self._next()

    def needs_ffmpeg(self) -> bool:
        return True

    def _next(self):
        it = next((self.items[i] for i in self.order if self.items[i]["status"] == "pending"), None)
        if it is None or self._stop:
            self._finish()
            return
        it["status"] = "running"
        it["row"].set_running()
        self.status.set_status(f"Working on {it['row'].name._full}…", theme.ACCENT, True)
        job = FuncJob(str(it["id"]), self.task(it, self._batch_opts))
        job.signals.progress.connect(self._on_progress)
        job.signals.done.connect(self._on_done)
        job.signals.failed.connect(lambda msg, detail, iid=it["id"]: self._on_failed(iid, msg, detail))
        job.signals.cancelled.connect(lambda iid=it["id"]: self._on_cancelled(iid))
        self.job = job
        self.pool.start(job)

    def _on_progress(self, payload):
        token, pct, text = payload
        it = self.items.get(int(token))
        if it:
            it["row"].set_progress(pct, text)

    def _on_done(self, payload):
        token, result = payload
        it = self.items.get(int(token))
        if it:
            it["status"] = "done"
            it["result"] = result
            text, path = self.describe(it, result)
            it["row"].set_done(text, path)
        self.job = None
        self._refresh()
        QTimer.singleShot(0, self._next)

    def _on_failed(self, iid, msg, detail):
        it = self.items.get(iid)
        if it:
            it["status"] = "error"
            it["row"].set_error(msg)
            it["row"].sub.setToolTip(detail[-1500:] if detail else msg)
        self.job = None
        self._refresh()
        QTimer.singleShot(0, self._next)

    def _on_cancelled(self, iid):
        it = self.items.get(iid)
        if it:
            it["status"] = "pending"
            it["row"].set_pending("Cancelled · press Start to try again")
        self.job = None
        self._finish()

    def cancel(self):
        self._stop = True
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Cancelling…")
        if self.job is not None:
            self.job.cancel()
        else:
            self._finish()

    def _finish(self):
        self.running = False
        self.cancel_btn.hide()
        self.start_btn.show()
        done = sum(1 for it in self.items.values() if it["status"] == "done")
        errs = sum(1 for it in self.items.values() if it["status"] == "error")
        if self._stop:
            self.status.set_status("Stopped.", theme.TEXT_3)
        else:
            self.status.set_status(f"Finished: {done} done" + (f", {errs} failed" if errs else "") + ".",
                                   theme.DANGER if errs else theme.ACCENT)
        self.after_batch()
        self._refresh()

    def can_close(self) -> bool:
        if self.running:
            box = QMessageBox(self)
            box.setWindowTitle(self.TITLE)
            box.setText("This tool is still working. Stop and close?")
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                return False
            self.cancel()
        self.remember()
        return True


def option_group(title: str, widget: QWidget, note: QWidget | None = None) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)
    head = QHBoxLayout()
    head.addWidget(label(title, "FieldLabel"))
    head.addStretch(1)
    if note is not None:
        head.addWidget(note)
    v.addLayout(head)
    v.addWidget(widget)
    return w


def toggle_row(text: str, on: bool, tip: str = "") -> tuple[QWidget, Toggle]:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    t = Toggle(on, 34, 20)
    t.setAccessibleName(text)
    h.addWidget(t)
    h.addSpacing(6)
    lb = label(text)
    lb.setToolTip(tip)
    h.addWidget(lb)
    h.addStretch(1)
    return w, t
