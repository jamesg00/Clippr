"""Animated drag-and-drop overlay: dark green veil, marching-ants frame, ripples and particles that follow the
cursor, a bobbing target and a burst when you let go. Red tint when nothing in the drag can be used."""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import theme


class _P:
    __slots__ = ("x", "y", "vx", "vy", "r", "life", "phase")

    def __init__(self, x, y, vx=0.0, vy=0.0, r=2.0, life=1.0):
        self.x, self.y, self.vx, self.vy, self.r, self.life = x, y, vx, vy, r, life
        self.phase = random.random() * math.tau


class DropOverlay(QWidget):
    """Covers its parent while something is dragged over it. Call enter()/move()/leave()/drop() from the
    parent's drag events; the overlay itself is transparent to the mouse."""

    def __init__(self, parent: QWidget, radius: int = 14, inset: int = 8):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.radius, self.inset = radius, inset
        self.hide()
        self._t0 = time.monotonic()
        self._last = self._t0
        self._fade = 0.0  # 0..1 visibility
        self._target = 0.0
        self._ok = True
        self._title = ""
        self._sub = ""
        self._icon = "upload"
        self._cursor = QPointF(0, 0)
        self._ripples: list[list[float]] = []  # [x, y, age]
        self._parts: list[_P] = []
        self._burst: list[_P] = []
        self._next_ripple = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        parent.installEventFilter(self)

    # ------------------------------------------------------------ public api
    def enter(self, pos: QPointF, ok: bool, title: str, sub: str = "", icon: str = "upload"):
        self._ok, self._title, self._sub, self._icon = ok, title, sub, icon
        self.setGeometry(self.parentWidget().rect())
        self._cursor = QPointF(pos)
        if not self.isVisible():
            self._parts = []
            self._burst = []
            self._ripples = []
            w, h = max(1, self.width()), max(1, self.height())
            for _ in range(46):
                self._parts.append(_P(random.uniform(0, w), random.uniform(0, h), random.uniform(-20, 20),
                                      random.uniform(-20, 20), random.uniform(1.2, 2.8)))
        self._target = 1.0
        self.raise_()
        self.show()
        if not self._timer.isActive():
            self._last = time.monotonic()
            self._timer.start()

    def move(self, pos: QPointF):  # noqa: A003 - mirrors drag "move"
        self._cursor = QPointF(pos)

    def leave(self):
        self._target = 0.0

    def drop(self, pos: QPointF | None = None):
        """Burst of particles from the drop point, then fade out."""
        p = QPointF(pos) if pos is not None else self._cursor
        if self._ok:
            for i in range(54):
                a = i / 54 * math.tau + random.uniform(-0.1, 0.1)
                sp = random.uniform(160, 520)
                self._burst.append(_P(p.x(), p.y(), math.cos(a) * sp, math.sin(a) * sp, random.uniform(1.5, 3.4),
                                      1.0))
            self._ripples.append([p.x(), p.y(), 0.0])
            self._ripples.append([p.x(), p.y(), -0.12])
        self._target = 0.0

    @property
    def active(self) -> bool:
        return self.isVisible() and self._target > 0

    # ------------------------------------------------------------ internals
    def eventFilter(self, obj, e):  # noqa: N802
        if obj is self.parentWidget() and e.type() == e.Type.Resize and self.isVisible():
            self.setGeometry(obj.rect())
        return False

    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        speed = 7.0 if self._target > self._fade else 4.0
        self._fade += (self._target - self._fade) * min(1.0, dt * speed)
        cx, cy = self._cursor.x(), self._cursor.y()
        # particles drift toward the cursor (or away, if the drop isn't allowed)
        pull = 1.0 if self._ok else -0.6
        for q in self._parts:
            dx, dy = cx - q.x, cy - q.y
            d = math.hypot(dx, dy) + 1
            f = 900 * pull / max(60.0, d)
            q.vx += (dx / d * f + math.sin(now * 1.7 + q.phase) * 14) * dt
            q.vy += (dy / d * f + math.cos(now * 1.3 + q.phase) * 14) * dt
            q.vx *= 0.94
            q.vy *= 0.94
            q.x += q.vx * dt
            q.y += q.vy * dt
            if d < 26 and self._ok:  # swallowed by the cursor: respawn at an edge
                side = random.randrange(4)
                w, h = self.width(), self.height()
                q.x, q.y = [(random.uniform(0, w), 0), (w, random.uniform(0, h)), (random.uniform(0, w), h),
                            (0, random.uniform(0, h))][side]
                q.vx = q.vy = 0
            q.x = min(max(q.x, 0), self.width())
            q.y = min(max(q.y, 0), self.height())
        for b in self._burst:
            b.x += b.vx * dt
            b.y += b.vy * dt
            b.vx *= 0.9
            b.vy *= 0.9
            b.life -= dt * 1.6
        self._burst = [b for b in self._burst if b.life > 0]
        if self._target > 0 and self._ok and now >= self._next_ripple:
            self._ripples.append([cx, cy, 0.0])
            self._next_ripple = now + 0.55
        for r in self._ripples:
            r[2] += dt
        self._ripples = [r for r in self._ripples if r[2] < 1.1]
        if self._target == 0 and self._fade < 0.02 and not self._burst:
            self._fade = 0
            self._timer.stop()
            self.hide()
            return
        self.update()

    def paintEvent(self, e):  # noqa: N802
        a = self._fade
        if a <= 0.001 and not self._burst:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        now = time.monotonic() - self._t0
        acc = QColor(theme.ACCENT) if self._ok else QColor(theme.DANGER)
        rect = QRectF(self.rect()).adjusted(self.inset, self.inset, -self.inset, -self.inset)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        p.setClipPath(path)

        # veil + glow under the cursor
        veil = QColor(2, 12, 7) if self._ok else QColor(16, 4, 4)
        veil.setAlphaF(0.80 * a)
        p.fillPath(path, veil)
        g = QRadialGradient(self._cursor, max(rect.width(), rect.height()) * 0.55)
        c = QColor(acc)
        c.setAlphaF(0.22 * a)
        g.setColorAt(0, c)
        c2 = QColor(acc)
        c2.setAlphaF(0)
        g.setColorAt(1, c2)
        p.fillRect(rect, g)

        # dot grid that brightens near the cursor
        step = 26
        p.setPen(Qt.NoPen)
        y = rect.top() + step / 2
        while y < rect.bottom():
            x = rect.left() + step / 2
            while x < rect.right():
                d = math.hypot(x - self._cursor.x(), y - self._cursor.y())
                k = max(0.0, 1 - d / 260)
                dc = QColor(acc)
                dc.setAlphaF((0.07 + 0.45 * k * k) * a)
                p.setBrush(dc)
                rr = 1.1 + 1.3 * k
                p.drawEllipse(QPointF(x, y), rr, rr)
                x += step
            y += step

        # ripples
        for rx, ry, age in self._ripples:
            if age < 0:
                continue
            t = age / 1.1
            rc = QColor(acc)
            rc.setAlphaF((1 - t) * 0.55 * max(a, 0.4))
            p.setPen(QPen(rc, 2.0 * (1 - t) + 0.6))
            p.setBrush(Qt.NoBrush)
            rad = 12 + t * 170
            p.drawEllipse(QPointF(rx, ry), rad, rad)

        # particles
        p.setPen(Qt.NoPen)
        for q in self._parts:
            pc = QColor(acc)
            tw = 0.55 + 0.45 * math.sin(now * 3 + q.phase)
            pc.setAlphaF(0.75 * a * tw)
            p.setBrush(pc)
            p.drawEllipse(QPointF(q.x, q.y), q.r, q.r)
        for b in self._burst:
            pc = QColor(theme.ACCENT)
            pc.setAlphaF(max(0.0, b.life))
            p.setBrush(pc)
            p.drawEllipse(QPointF(b.x, b.y), b.r, b.r)
        p.setClipping(False)

        # marching-ants frame
        pen = QPen(acc, 2.0)
        pen.setDashPattern([6, 5])
        pen.setDashOffset(-now * 22)
        fc = QColor(acc)
        fc.setAlphaF(0.95 * a)
        pen.setColor(fc)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), self.radius, self.radius)

        # centre badge: bobbing icon + text
        if a > 0.02:
            ctr = rect.center()
            bob = math.sin(now * 3.2) * 5
            pulse = 1 + 0.06 * math.sin(now * 4.4)
            R = 40 * pulse
            halo = QRadialGradient(QPointF(ctr.x(), ctr.y() - 30 + bob), R * 2.4)
            hc = QColor(acc)
            hc.setAlphaF(0.35 * a)
            halo.setColorAt(0, hc)
            hc2 = QColor(acc)
            hc2.setAlphaF(0)
            halo.setColorAt(1, hc2)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QPointF(ctr.x(), ctr.y() - 30 + bob), R * 2.4, R * 2.4)
            disc = QColor(acc)
            disc.setAlphaF(0.95 * a)
            p.setBrush(disc)
            p.drawEllipse(QPointF(ctr.x(), ctr.y() - 30 + bob), R, R)
            ic = theme.icon_pixmap(self._icon if self._ok else "x", theme.ON_ACCENT, 30, 2.4)
            p.setOpacity(a)
            p.drawPixmap(QPointF(ctr.x() - 15, ctr.y() - 45 + bob), ic)
            p.setOpacity(1.0)
            f = QFont(theme.FONT_DISPLAY)
            f.setPixelSize(22)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            tc = QColor(theme.TEXT)
            tc.setAlphaF(a)
            p.setPen(tc)
            p.drawText(QRectF(rect.left(), ctr.y() + 22, rect.width(), 30), Qt.AlignCenter, self._title)
            if self._sub:
                f2 = QFont(theme.FONT_UI)
                f2.setPixelSize(13)
                p.setFont(f2)
                sc = QColor(theme.TEXT_2)
                sc.setAlphaF(a)
                p.setPen(sc)
                p.drawText(QRectF(rect.left() + 20, ctr.y() + 54, rect.width() - 40, 22), Qt.AlignCenter, self._sub)
        p.end()
