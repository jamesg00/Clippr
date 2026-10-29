"""Custom-painted trim track: waveform, clip handles, playhead and download sweep."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme

HANDLE_W = 10
MIN_CLIP = 0.2


def _placeholder(n: int) -> list[float]:
    return [max(0.12, min(1.0, 0.22 + 0.78 * abs(math.sin(i * 0.37) * math.cos(i * 0.113 + 1.3))
                         * (0.7 + 0.3 * abs(math.sin(i * 1.7))))) for i in range(n)]


class TrimTrack(QWidget):
    rangeChanged = Signal(float, float)
    rangeEdited = Signal()  # drag released

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(84)
        self.setFixedHeight(84)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.duration = 1.0
        self.start = 0.0
        self.end = 1.0
        self.playhead: float | None = 0.0
        self.peaks: list[float] | None = None
        self._placeholder = _placeholder(400)
        self.locked = False
        self.sweep: float | None = None  # 0..1 of the clip during download
        self._drag = None  # "start" | "end" | "move"
        self._grab = 0.0

    # ---- API
    def set_duration(self, d: float):
        self.duration = max(0.1, d)
        self.update()

    def set_range(self, s: float, e: float):
        self.start, self.end = s, e
        self.update()

    def set_playhead(self, t: float | None):
        self.playhead = t
        self.update()

    def set_peaks(self, peaks: list[float] | None):
        self.peaks = peaks
        self.update()

    def set_locked(self, on: bool):
        self.locked = on
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def set_sweep(self, frac: float | None):
        self.sweep = frac
        self.update()

    # ---- geometry
    def _x(self, t: float) -> float:
        return t / self.duration * self.width()

    def _t(self, x: float) -> float:
        return max(0.0, min(self.duration, x / max(1, self.width()) * self.duration))

    # ---- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(r, 8, 8)
        p.setPen(QPen(theme.white(0.06), 1))
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawPath(clip)
        p.setClipPath(clip)

        w, h = self.width(), self.height()
        peaks = self.peaks or self._placeholder
        n = max(1, int(w // 4))
        top, bot = 12, h - 12
        mid, half = (top + bot) / 2, (bot - top) / 2
        acc = QColor(theme.ACCENT)
        dim = theme.white(0.13 if self.peaks else 0.08)
        pend = theme.qcolor(theme.ACCENT, 0.3)
        sweep_t = self.start + (self.end - self.start) * self.sweep if self.sweep is not None else None
        p.setPen(Qt.NoPen)
        for i in range(n):
            t = (i + 0.5) / n * self.duration
            v = peaks[min(len(peaks) - 1, int(i / n * len(peaks)))]
            bh = max(2.0, v * half * 2)
            in_clip = self.start <= t <= self.end
            if in_clip:
                c = pend if (sweep_t is not None and t > sweep_t) else acc
            else:
                c = dim
            p.setBrush(c)
            p.drawRoundedRect(QRectF(i * 4 + 1, mid - bh / 2, 2, bh), 1, 1)

        xs, xe = self._x(self.start), self._x(self.end)
        p.setBrush(theme.qcolor(theme.ACCENT, 0.08))
        p.drawRect(QRectF(xs, 0, xe - xs, h))
        p.setBrush(acc)
        p.drawRect(QRectF(xs, 0, xe - xs, 2))
        p.drawRect(QRectF(xs, h - 2, xe - xs, 2))
        # handles
        for x, left in ((xs, True), (xe - HANDLE_W, False)):
            path = QPainterPath()
            hr = QRectF(x, 0, HANDLE_W, h)
            rad = 6
            if left:
                path.addRoundedRect(hr, rad, rad)
                path.addRect(QRectF(x + rad, 0, HANDLE_W - rad, h))
            else:
                path.addRoundedRect(hr, rad, rad)
                path.addRect(QRectF(x, 0, HANDLE_W - rad, h))
            path.setFillRule(Qt.WindingFill)
            p.setBrush(acc if not self.locked else theme.qcolor(theme.ACCENT, 0.6))
            p.drawPath(path.simplified())
            p.setBrush(QColor(4, 20, 12, 140))
            p.drawRoundedRect(QRectF(x + HANDLE_W / 2 - 1, mid - 7, 2, 14), 1, 1)

        if sweep_t is not None:
            x = self._x(sweep_t)
            p.setBrush(theme.qcolor(theme.ACCENT, 0.35))
            p.drawRect(QRectF(x - 4, 0, 8, h))
            p.setBrush(QColor("#FFFFFF"))
            p.drawRect(QRectF(x - 1, 0, 2, h))
        elif self.playhead is not None and not self.locked:
            x = self._x(self.playhead)
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawRect(QRectF(x - 1, 0, 2, h))

    # ---- mouse
    def _hit(self, x: float) -> str:
        xs, xe = self._x(self.start), self._x(self.end)
        if xs - 4 <= x <= xs + HANDLE_W + 2:
            return "start"
        if xe - HANDLE_W - 2 <= x <= xe + 4:
            return "end"
        if xs < x < xe:
            return "move"
        return "outside"

    def mousePressEvent(self, e):
        if self.locked or e.button() != Qt.LeftButton:
            return
        x = e.position().x()
        hit = self._hit(x)
        t = self._t(x)
        if hit == "outside":
            hit = "start" if abs(t - self.start) < abs(t - self.end) else "end"
            self._apply(hit, t)
        self._drag = hit
        self._grab = t - self.start
        self.setCursor(Qt.ClosedHandCursor if hit == "move" else Qt.SizeHorCursor)

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._drag:
            t = self._t(x)
            if self._drag == "move":
                length = self.end - self.start
                s = max(0.0, min(self.duration - length, t - self._grab))
                self.start, self.end = s, s + length
                self.rangeChanged.emit(self.start, self.end)
                self.update()
            else:
                self._apply(self._drag, t)
        elif not self.locked:
            hit = self._hit(x)
            self.setCursor({"start": Qt.SizeHorCursor, "end": Qt.SizeHorCursor,
                            "move": Qt.OpenHandCursor}.get(hit, Qt.PointingHandCursor))

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            self.setCursor(Qt.ArrowCursor)
            self.rangeEdited.emit()

    def _apply(self, which: str, t: float):
        t = round(t, 1)
        if which == "start":
            self.start = max(0.0, min(t, self.end - MIN_CLIP))
        else:
            self.end = min(self.duration, max(t, self.start + MIN_CLIP))
        self.rangeChanged.emit(self.start, self.end)
        self.update()


class Ruler(QWidget):
    """Time labels under the trim track at a 'nice' step for the video length."""

    STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.duration = 1.0

    def set_duration(self, d: float):
        self.duration = max(0.1, d)
        self.update()

    def paintEvent(self, _):
        from ..core.timefmt import fmt_time
        p = QPainter(self)
        p.setFont(theme.font(10.5, mono=True))
        p.setPen(QColor(theme.TEXT_3))
        max_labels = max(2, self.width() // 70)
        step = next((s for s in self.STEPS if self.duration / s <= max_labels), self.STEPS[-1])
        t = 0.0
        while t <= self.duration + 1e-6:
            x = t / self.duration * self.width()
            txt = fmt_time(t)
            fw = p.fontMetrics().horizontalAdvance(txt)
            if t == 0:
                tx = x
            else:
                tx = x - fw / 2
            if tx + fw <= self.width():
                p.drawText(QPointF(tx, 11), txt)
            t += step


class SeekBar(QWidget):
    """Thin full-length seek bar under the video; shows the clip range as a band."""

    seekRequested = Signal(float)
    scrubbing = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)
        self.setCursor(Qt.PointingHandCursor)
        self.duration = 1.0
        self.position = 0.0
        self.start = 0.0
        self.end = 0.0
        self._down = False
        self.setToolTip("Seek")

    def set_state(self, duration=None, position=None, start=None, end=None):
        if duration is not None:
            self.duration = max(0.1, duration)
        if position is not None and not self._down:
            self.position = position
        if start is not None:
            self.start = start
        if end is not None:
            self.end = end
        self.update()

    def _x(self, t):
        return 14 + t / self.duration * (self.width() - 28)

    def _t(self, x):
        return max(0.0, min(self.duration, (x - 14) / max(1, self.width() - 28) * self.duration))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        y = 8
        left, right = 14, self.width() - 14
        p.setBrush(theme.white(0.12))
        p.drawRoundedRect(QRectF(left, y, right - left, 4), 2, 2)
        p.setBrush(theme.qcolor(theme.ACCENT, 0.4))
        p.drawRect(QRectF(self._x(self.start), y, self._x(self.end) - self._x(self.start), 4))
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(left, y, self._x(self.position) - left, 4), 2, 2)
        p.setBrush(QColor(0, 0, 0, 120))
        cx = self._x(self.position)
        p.drawEllipse(QPointF(cx, y + 2.5), 7, 7)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(cx, y + 2), 6, 6)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._down = True
            self.scrubbing.emit(True)
            self.position = self._t(e.position().x())
            self.seekRequested.emit(self.position)
            self.update()

    def mouseMoveEvent(self, e):
        if self._down:
            self.position = self._t(e.position().x())
            self.seekRequested.emit(self.position)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._down:
            self._down = False
            self.scrubbing.emit(False)
