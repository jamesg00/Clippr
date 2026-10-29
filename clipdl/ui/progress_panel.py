"""Right-panel states: live download readout (progress ring), done card (animated tick), error card."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from ..core.timefmt import fmt_time
from . import theme
from .rings import ProgressRing, SuccessTick
from .widgets import Dot, label


def _mb(n: int | float) -> str:
    return f"{n / 1_000_000:.1f}"


class GroupedList(QFrame):
    """macOS-style inset grouped rows: label on the left, value on the right, hairlines between."""

    def __init__(self, rows: list[str]):
        super().__init__()
        self.setObjectName("Group")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 2, 0, 2)
        v.setSpacing(0)
        self.values: dict[str, QLabel] = {}
        for i, name in enumerate(rows):
            if i:
                sep = QFrame()
                sep.setObjectName("GroupSep")
                sep.setAttribute(Qt.WA_StyledBackground, True)
                v.addWidget(sep)
            row = QHBoxLayout()
            row.setContentsMargins(14, 9, 14, 9)
            k = label(name)
            k.setStyleSheet(f"color:{theme.TEXT_2};font-size:13px;")
            val = label("—")
            val.setStyleSheet(f"font-family:'{theme.FONT_MONO}';font-size:13px;color:{theme.TEXT};")
            row.addWidget(k)
            row.addStretch(1)
            row.addWidget(val)
            v.addLayout(row)
            self.values[name] = val

    def set(self, name: str, text: str):
        self.values[name].setText(text)


class ProgressPanel(QWidget):
    cancelRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        head = QHBoxLayout()
        self.title = label("Downloading")
        self.title.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:17px;font-weight:600;"
                                 "letter-spacing:-0.2px;")
        head.addWidget(self.title)
        head.addStretch(1)
        self.live_dot = Dot()
        self.live_dot.set_pulse(True)
        live = label("Live")
        live.setStyleSheet(f"color:{theme.ACCENT};font-size:11px;font-weight:600;")
        head.addWidget(self.live_dot)
        head.addWidget(live)
        v.addLayout(head)

        card = QFrame()
        card.setObjectName("Well")
        card.setAttribute(Qt.WA_StyledBackground, True)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 10, 14, 10)
        cv.setSpacing(3)
        self.file_lbl = label("")
        self.file_lbl.setStyleSheet("font-size:13px;font-weight:500;")
        self.sub_lbl = label("", "MonoFaint")
        cv.addWidget(self.file_lbl)
        cv.addWidget(self.sub_lbl)
        v.addWidget(card)

        v.addSpacing(6)
        self.ring = ProgressRing(176)
        v.addWidget(self.ring, 0, Qt.AlignHCenter)
        v.addSpacing(6)

        self.stats = GroupedList(["Speed", "Time left", "Output so far", "Elapsed"])
        v.addWidget(self.stats)

        self.details_btn = QPushButton("›  Show details")
        self.details_btn.setObjectName("Disclosure")
        self.details_btn.setCursor(Qt.PointingHandCursor)
        self.details_btn.setCheckable(True)
        self.details_btn.toggled.connect(self._toggle_details)
        v.addWidget(self.details_btn)

        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(200)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log.setAccessibleName("Download log")
        self.log.hide()
        v.addWidget(self.log, 1)
        self.spacer = QWidget()
        v.addWidget(self.spacer, 1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("Pill")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancelRequested.emit)
        v.addWidget(self.cancel_btn)

    def _toggle_details(self, on: bool):
        self.log.setVisible(on)
        self.spacer.setVisible(not on)
        self.details_btn.setText(("⌄  Hide details" if on else "›  Show details"))

    def start(self, file_name: str, sub: str):
        self.file_lbl.setText(file_name)
        self.file_lbl.setToolTip(file_name)
        self.sub_lbl.setText(sub)
        self.log.clear()
        self.ring.reset()
        self.title.setText("Starting…")
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel")
        for k in self.stats.values:
            self.stats.set(k, "—")

    def update_progress(self, p):
        titles = {"preparing": "Finding streams…", "downloading": "Downloading",
                  "encoding": "Encoding", "finishing": "Finishing up"}
        self.title.setText(titles.get(p.phase, "Downloading"))
        if p.indeterminate or p.phase == "preparing":
            self.ring.set_mode("spin")
        elif p.phase == "finishing":
            self.ring.set_mode("finishing")
            self.ring.set_value(100)
        else:
            self.ring.set_mode("progress")
            self.ring.set_value(p.percent)
        if p.out_bytes:
            tot = f" / {_mb(p.est_total_bytes)}" if p.est_total_bytes else ""
            self.ring.set_caption(f"{_mb(p.out_bytes)}{tot} MB")
        elif p.phase == "preparing":
            self.ring.set_caption("Preparing")
        if p.net_bytes_per_s:
            self.stats.set("Speed", f"{p.net_bytes_per_s / 1_000_000:.1f} MB/s")
        elif p.speed_x:
            self.stats.set("Speed", f"{p.speed_x:.1f}× realtime")
        if p.phase == "finishing":
            self.stats.set("Time left", "0:00")
        elif p.eta_s is not None:
            self.stats.set("Time left", fmt_time(p.eta_s))
        self.stats.set("Output so far", f"{_mb(p.out_bytes)} MB" if p.out_bytes else "—")
        self.stats.set("Elapsed", fmt_time(p.elapsed_s))

    def append_log(self, line: str):
        self.log.appendPlainText(line)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def set_cancelling(self):
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Cancelling…")
        self.title.setText("Cancelling…")


class DonePanel(QWidget):
    showInFolder = Signal()
    again = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addStretch(1)
        self.tick = SuccessTick(104)
        v.addWidget(self.tick, 0, Qt.AlignHCenter)
        t = label("Clip saved")
        t.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:24px;font-weight:600;letter-spacing:-0.4px;")
        v.addWidget(t, 0, Qt.AlignHCenter)
        self.name = label("", wrap=True)
        self.name.setAlignment(Qt.AlignCenter)
        self.name.setStyleSheet("font-size:13px;color:#C4CEC9;")
        self.name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.name)
        v.addSpacing(8)
        self.stats = GroupedList(["Size", "Clip", "Format", "Took"])
        v.addWidget(self.stats)
        v.addStretch(1)
        show = QPushButton("  Show in folder")
        show.setObjectName("Primary")
        show.setMinimumHeight(44)
        show.setProperty("pill", True)
        show.setIcon(theme.icon("folder", theme.ON_ACCENT, 16, 2.2))
        show.setIconSize(QSize(16, 16))
        show.setCursor(Qt.PointingHandCursor)
        show.setToolTip(f"Show in folder ({theme.keys('Ctrl+Shift+O')})")
        show.clicked.connect(self.showInFolder.emit)
        another = QPushButton("Make another clip")
        another.setObjectName("Pill")
        another.setCursor(Qt.PointingHandCursor)
        another.clicked.connect(self.again.emit)
        v.addWidget(show)
        v.addWidget(another)

    def set_result(self, file_name: str, size: str, clip: str, fmt: str, took: str):
        self.name.setText(file_name)
        self.stats.set("Size", size)
        self.stats.set("Clip", clip)
        self.stats.set("Format", fmt)
        self.stats.set("Took", took)
        self.tick.play()


class ErrorPanel(QWidget):
    retry = Signal()
    back = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        v.addStretch(1)
        circle = QLabel()
        circle.setFixedSize(64, 64)
        circle.setAlignment(Qt.AlignCenter)
        circle.setPixmap(theme.icon_pixmap("alert", theme.DANGER, 30, 2.0))
        circle.setStyleSheet(f"background:{theme.rgba(theme.DANGER, 0.14)};border-radius:32px;")
        v.addWidget(circle, 0, Qt.AlignHCenter)
        self.title = label("Couldn't make the clip")
        self.title.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:19px;font-weight:600;")
        self.title.setAlignment(Qt.AlignCenter)
        v.addWidget(self.title)
        self.msg = label("", "Muted", wrap=True)
        self.msg.setAlignment(Qt.AlignCenter)
        v.addWidget(self.msg)
        self.detail = QPlainTextEdit()
        self.detail.setObjectName("Log")
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(110)
        self.detail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.detail.setAccessibleName("Error details")
        v.addWidget(self.detail)
        v.addStretch(1)
        self.retry_btn = QPushButton("  Try again")
        self.retry_btn.setObjectName("Primary")
        self.retry_btn.setMinimumHeight(44)
        self.retry_btn.setProperty("pill", True)
        self.retry_btn.setIcon(theme.icon("refresh", theme.ON_ACCENT, 16, 2.2))
        self.retry_btn.setCursor(Qt.PointingHandCursor)
        self.retry_btn.clicked.connect(self.retry.emit)
        back = QPushButton("Back to settings")
        back.setObjectName("Pill")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back.emit)
        v.addWidget(self.retry_btn)
        v.addWidget(back)

    def set_error(self, title: str, message: str, detail: str = ""):
        self.title.setText(title)
        self.msg.setText(message)
        self.detail.setPlainText(detail.strip()[-4000:])
        self.detail.setVisible(bool(detail.strip()))
