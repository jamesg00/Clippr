"""Apple-style animated progress ring and success tick."""
from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme


class ProgressRing(QWidget):
    """Circular progress with eased motion, an indeterminate spinner, and a soft glow.

    Modes: "progress" (0..100), "spin" (indeterminate), "finishing" (full ring, breathing).
    """

    def __init__(self, size: int = 176, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._target = 0.0
        self._shown = 0.0
        self._mode = "spin"
        self._angle = 0.0
        self._breath = 0.0
        self.caption = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_value(self, v: float):
        self._target = max(0.0, min(100.0, v))

    def set_mode(self, mode: str):
        self._mode = mode
        if mode == "spin":
            self._shown = self._target = 0.0
        self.update()

    def set_caption(self, text: str):
        self.caption = text
        self.update()

    def reset(self):
        self._target = self._shown = 0.0
        self._mode = "spin"
        self.caption = ""
        self.update()

    def _tick(self):
        if not self.isVisible():
            return
        self._angle = (self._angle + 5.0) % 360
        self._breath = (self._breath + 0.035) % (2 * math.pi)
        diff = self._target - self._shown
        self._shown += diff * 0.14 if abs(diff) > 0.05 else diff
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.width()
        w = 10.0
        r = QRectF(w / 2 + 6, w / 2 + 6, s - w - 12, s - w - 12)
        acc = QColor(theme.ACCENT)

        # track
        p.setPen(QPen(theme.white(0.08), w, Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(r)

        if self._mode == "spin":
            span = 90 * 16
            start = int(-self._angle * 16)
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.25), w + 8, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, start, -span)
            p.setPen(QPen(acc, w, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, start, -span)
            pct_text = ""
        else:
            frac = 1.0 if self._mode == "finishing" else self._shown / 100
            span = int(-360 * 16 * frac)
            glow_a = 0.22 + (0.18 * (0.5 + 0.5 * math.sin(self._breath)) if self._mode == "finishing" else 0)
            if frac > 0:
                p.setPen(QPen(theme.qcolor(theme.ACCENT, glow_a), w + 10, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(r, 90 * 16, span)
                p.setPen(QPen(acc, w, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(r, 90 * 16, span)
                # bright head dot (like Apple's activity rings)
                if 0.02 < frac < 1.0:
                    ang = math.radians(90 - 360 * frac)
                    cx = r.center().x() + r.width() / 2 * math.cos(ang)
                    cy = r.center().y() - r.height() / 2 * math.sin(ang)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(255, 255, 255, 230))
                    p.drawEllipse(QPointF(cx, cy), w * 0.22, w * 0.22)
            pct_text = f"{int(self._shown)}%" if self._mode == "progress" else "100%"

        # center text
        if pct_text:
            p.setPen(QColor("#FFFFFF"))
            f = theme.font(40, 600, display=True)
            f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, -1.0)
            p.setFont(f)
            p.drawText(QRectF(0, s / 2 - 34, s, 48), Qt.AlignHCenter | Qt.AlignVCenter, pct_text)
        if self.caption:
            p.setPen(QColor(theme.TEXT_2))
            p.setFont(theme.font(11.5, 500, mono=True))
            y = s / 2 + (16 if pct_text else -9)
            p.drawText(QRectF(0, y, s, 18), Qt.AlignHCenter | Qt.AlignVCenter, self.caption)


class SuccessTick(QWidget):
    """Filled accent circle that springs in, then a white tick that draws itself, plus a fading halo."""

    def __init__(self, size: int = 96, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(900)
        self._anim.setEasingCurve(QEasingCurve.Linear)
        self._anim.valueChanged.connect(self._on)
        self._back = QEasingCurve(QEasingCurve.OutBack)
        self._back.setOvershoot(2.2)
        self._out = QEasingCurve(QEasingCurve.OutCubic)

    def play(self):
        self._anim.stop()
        self._t = 0.0
        self._anim.start()

    def _on(self, v):
        self._t = float(v)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.width()
        c = QPointF(s / 2, s / 2)
        base_r = s * 0.36
        t = self._t

        # halo: expands and fades after the circle lands
        ht = max(0.0, min(1.0, (t - 0.25) / 0.75))
        if 0 < ht < 1:
            hr = base_r * (1.0 + 0.32 * self._out.valueForProgress(ht))
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.45 * (1 - ht)), 2.0))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, hr, hr)

        # circle (spring scale-in)
        ct = max(0.0, min(1.0, t / 0.45))
        scale = self._back.valueForProgress(ct)
        if scale > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qcolor(theme.ACCENT, 0.18))
            p.drawEllipse(c, base_r * scale * 1.18, base_r * scale * 1.18)
            p.setBrush(QColor("#22C984"))  # a touch deeper than the accent so the white tick reads clearly
            p.drawEllipse(c, base_r * scale, base_r * scale)

        # tick draws itself
        kt = max(0.0, min(1.0, (t - 0.35) / 0.45))
        if kt > 0:
            k = self._out.valueForProgress(kt)
            pts = [QPointF(s * 0.355, s * 0.51), QPointF(s * 0.455, s * 0.61), QPointF(s * 0.65, s * 0.405)]
            l1 = math.dist((pts[0].x(), pts[0].y()), (pts[1].x(), pts[1].y()))
            l2 = math.dist((pts[1].x(), pts[1].y()), (pts[2].x(), pts[2].y()))
            d = k * (l1 + l2)
            path = QPainterPath(pts[0])
            if d <= l1:
                f = d / l1
                path.lineTo(pts[0] + (pts[1] - pts[0]) * f)
            else:
                path.lineTo(pts[1])
                f = (d - l1) / l2
                path.lineTo(pts[1] + (pts[2] - pts[1]) * f)
            p.setPen(QPen(QColor("#FFFFFF"), s * 0.075, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
