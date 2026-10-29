"""Photoshop-style editor for the Resize tool.

The canvas ("artboard") is the output picture. The image sits on it as a layer you can move, scale from any of its
8 handles, rotate (round knob, or drag just outside a corner) and flip. The tabs just outside the artboard change the
canvas size (crop or extend) without touching the image. W / H with the chain button resize everything together,
proportionally while the chain is locked.

Keys: arrows nudge 1 px (Shift 10) · Shift while scaling = unlock proportions (or lock if unlocked) ·
Alt = scale from the centre · Shift while rotating = 15° steps · wheel = zoom · drag empty space or middle mouse = pan ·
double-click empty space = fit view · Ctrl+Z / Ctrl+Shift+Z = undo / redo.
"""
from __future__ import annotations

import math
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QImage, QKeySequence, QPainter, QPainterPath, QPen, \
    QPolygonF, QShortcut
from PySide6.QtWidgets import (QDoubleSpinBox, QFrame, QHBoxLayout, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout,
                               QWidget)

from ...core.images import Transform, fit_transform
from .. import theme
from ..widgets import Segmented, icon_button, label

HANDLE = 5  # half size of a layer handle, screen px
HIT = 8


def load_preview(path: str, max_side: int = 1800) -> tuple[QImage, int, int]:
    """(preview image, original width, original height). Uses Pillow so HEIC / EXIF rotation work."""
    from PIL import Image, ImageOps

    from ...core import images  # noqa: F401  (registers HEIF)
    with Image.open(path) as im0:
        im = ImageOps.exif_transpose(im0)
        iw, ih = im.size
        im = im.convert("RGBA")
        if max(iw, ih) > max_side:
            f = max_side / max(iw, ih)
            im = im.resize((max(1, round(iw * f)), max(1, round(ih * f))), Image.BILINEAR)
        data = im.tobytes("raw", "RGBA")
        q = QImage(data, im.width, im.height, im.width * 4, QImage.Format_RGBA8888).copy()
    return q, iw, ih


def _rot(x: float, y: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return x * c - y * s, x * s + y * c


class EditorCanvas(QWidget):
    changed = Signal(object)  # Transform, while editing
    begin = Signal()  # a gesture is about to change the transform (for undo)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.img: QImage | None = None
        self.iw = self.ih = 1
        self.t: Transform | None = None
        self.lock = True
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self._fitted = False
        self._drag = None  # dict describing the gesture
        self._hover = None
        self._guides: list[tuple[str, float]] = []
        self._hud = ""

    # ------------------------------------------------------------ api
    def set_image(self, img: QImage | None, iw: int, ih: int, t: Transform | None, refit: bool = True):
        self.img, self.iw, self.ih, self.t = img, max(1, iw), max(1, ih), t
        if refit:
            self._fitted = False
        self.update()

    def set_transform(self, t: Transform):
        self.t = t
        self.update()

    def fit_view(self):
        if not self.t:
            return
        W, H = self.width(), self.height()
        m = 56
        self.zoom = max(0.01, min((W - 2 * m) / max(1, self.t.canvas_w), (H - 2 * m) / max(1, self.t.canvas_h)))
        self.pan = QPointF((W - self.t.canvas_w * self.zoom) / 2, (H - self.t.canvas_h * self.zoom) / 2)
        self._fitted = True
        self.update()

    # ------------------------------------------------------------ geometry
    def c2w(self, x: float, y: float) -> QPointF:
        return QPointF(self.pan.x() + x * self.zoom, self.pan.y() + y * self.zoom)

    def w2c(self, p: QPointF) -> tuple[float, float]:
        return (p.x() - self.pan.x()) / self.zoom, (p.y() - self.pan.y()) / self.zoom

    def _half(self, t: Transform | None = None) -> tuple[float, float]:
        t = t or self.t
        return self.iw * abs(t.sx) / 2, self.ih * abs(t.sy) / 2

    def _layer_pt(self, lx: float, ly: float, t: Transform | None = None) -> tuple[float, float]:
        t = t or self.t
        rx, ry = _rot(lx, ly, t.rot)
        return t.cx + rx, t.cy + ry

    def _to_local(self, x: float, y: float, t: Transform | None = None) -> tuple[float, float]:
        t = t or self.t
        return _rot(x - t.cx, y - t.cy, -t.rot)

    def _layer_handles(self):
        hw, hh = self._half()
        out = []
        for hx in (-1, 0, 1):
            for hy in (-1, 0, 1):
                if hx == 0 and hy == 0:
                    continue
                out.append((hx, hy, self.c2w(*self._layer_pt(hx * hw, hy * hh))))
        return out

    def _knob(self) -> QPointF:
        hw, hh = self._half()
        return self.c2w(*self._layer_pt(0, -hh - 30 / self.zoom))

    def _canvas_tabs(self):
        """Artboard handles sit just outside its edges so they never collide with the image's handles."""
        t = self.t
        off = 14
        out = []
        for ax in (-1, 0, 1):
            for ay in (-1, 0, 1):
                if ax == 0 and ay == 0:
                    continue
                p = self.c2w(t.canvas_w * (ax + 1) / 2, t.canvas_h * (ay + 1) / 2)
                out.append((ax, ay, QPointF(p.x() + ax * off, p.y() + ay * off)))
        return out

    def hit(self, pos: QPointF):
        if not self.t or not self.img:
            return ("pan",)
        for hx, hy, p in self._layer_handles():
            if abs(p.x() - pos.x()) <= HIT and abs(p.y() - pos.y()) <= HIT:
                return ("scale", hx, hy)
        k = self._knob()
        if math.hypot(k.x() - pos.x(), k.y() - pos.y()) <= HIT + 2:
            return ("rotate",)
        for ax, ay, p in self._canvas_tabs():
            if abs(p.x() - pos.x()) <= HIT + 3 and abs(p.y() - pos.y()) <= HIT + 3:
                return ("canvas", ax, ay)
        cx, cy = self.w2c(pos)
        lx, ly = self._to_local(cx, cy)
        hw, hh = self._half()
        if abs(lx) <= hw and abs(ly) <= hh:
            return ("move",)
        # just outside a corner -> rotate, like Photoshop
        for hx, hy, p in self._layer_handles():
            if hx and hy and math.hypot(p.x() - pos.x(), p.y() - pos.y()) <= 26:
                return ("rotate",)
        return ("pan",)

    def _cursor_for(self, h):
        kind = h[0]
        if kind == "move":
            return Qt.SizeAllCursor
        if kind == "rotate":
            return Qt.CrossCursor
        if kind == "pan":
            return Qt.ClosedHandCursor if self._drag and self._drag["kind"] == "pan" else Qt.OpenHandCursor
        hx, hy = h[1], h[2]
        rot = self.t.rot if kind == "scale" else 0.0
        ang = (math.degrees(math.atan2(hy, hx)) + rot) % 180
        if ang < 22.5 or ang >= 157.5:
            return Qt.SizeHorCursor
        if ang < 67.5:
            return Qt.SizeFDiagCursor
        if ang < 112.5:
            return Qt.SizeVerCursor
        return Qt.SizeBDiagCursor

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, e):  # noqa: N802
        self.setFocus()
        pos = QPointF(e.position())
        if e.button() == Qt.MiddleButton or not self.t:
            self._drag = {"kind": "pan", "p0": pos, "pan0": QPointF(self.pan)}
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() != Qt.LeftButton:
            return
        h = self.hit(pos)
        self._drag = {"kind": h[0], "h": h, "p0": pos, "t0": self.t.copy(), "pan0": QPointF(self.pan)}
        if h[0] != "pan":
            self.begin.emit()
        self.setCursor(self._cursor_for(h))

    def mouseMoveEvent(self, e):  # noqa: N802
        pos = QPointF(e.position())
        d = self._drag
        if d is None:
            h = self.hit(pos)
            if h != self._hover:
                self._hover = h
                self.setCursor(self._cursor_for(h))
                self.update()
            return
        mods = e.modifiers()
        if d["kind"] == "pan":
            self.pan = d["pan0"] + (pos - d["p0"])
            self.update()
            return
        t0: Transform = d["t0"]
        mx, my = self.w2c(pos)
        px, py = self.w2c(d["p0"])
        if d["kind"] == "move":
            dx, dy = mx - px, my - py
            if mods & Qt.ShiftModifier:
                if abs(dx) > abs(dy):
                    dy = 0
                else:
                    dx = 0
            t = replace(t0, cx=t0.cx + dx, cy=t0.cy + dy)
            t = self._snap(t, mods)
            self._hud = f"x {round(t.cx - self.iw * abs(t.sx) / 2)}  y {round(t.cy - self.ih * abs(t.sy) / 2)}"
        elif d["kind"] == "rotate":
            a0 = math.degrees(math.atan2(py - t0.cy, px - t0.cx))
            a1 = math.degrees(math.atan2(my - t0.cy, mx - t0.cx))
            r = t0.rot + (a1 - a0)
            if mods & Qt.ShiftModifier:
                r = round(r / 15) * 15
            r = (r + 180) % 360 - 180
            t = replace(t0, rot=r)
            self._hud = f"{r:.1f}°"
        elif d["kind"] == "scale":
            t = self._scale(t0, d["h"][1], d["h"][2], mx, my, mods)
            self._hud = (f"{round(self.iw * abs(t.sx))} × {round(self.ih * abs(t.sy))} px  ·  "
                         f"{abs(t.sx) * 100:.0f}%" + ("" if abs(abs(t.sx) - abs(t.sy)) < 1e-4 else
                                                      f" × {abs(t.sy) * 100:.0f}%"))
        elif d["kind"] == "canvas":
            t = self._canvas(t0, d["h"][1], d["h"][2], mx - px, my - py, mods)
            self._hud = f"{t.canvas_w} × {t.canvas_h} px"
        else:
            return
        self.t = t
        self.changed.emit(t.copy())
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag = None
        self._guides = []
        self._hud = ""
        self._hover = self.hit(QPointF(e.position()))
        self.setCursor(self._cursor_for(self._hover))
        self.update()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if self.hit(QPointF(e.position()))[0] == "pan":
            self.fit_view()

    def wheelEvent(self, e):  # noqa: N802
        if not self.t:
            return
        f = 1.0015 ** e.angleDelta().y()
        pos = QPointF(e.position())
        cx, cy = self.w2c(pos)
        self.zoom = max(0.02, min(32.0, self.zoom * f))
        self.pan = QPointF(pos.x() - cx * self.zoom, pos.y() - cy * self.zoom)
        self.update()

    def keyPressEvent(self, e):  # noqa: N802
        if not self.t:
            return super().keyPressEvent(e)
        step = 10 if e.modifiers() & Qt.ShiftModifier else 1
        dx, dy = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step),
                  Qt.Key_Down: (0, step)}.get(e.key(), (0, 0))
        if dx or dy:
            self.begin.emit()
            self.t = replace(self.t, cx=self.t.cx + dx, cy=self.t.cy + dy)
            self.changed.emit(self.t.copy())
            self.update()
            return
        super().keyPressEvent(e)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if not self._fitted or e.oldSize().width() <= 0:
            self.fit_view()

    # ------------------------------------------------------------ gestures
    def _scale(self, t0: Transform, hx: int, hy: int, mx: float, my: float, mods) -> Transform:
        hw0, hh0 = self.iw * abs(t0.sx) / 2, self.ih * abs(t0.sy) / 2
        lx, ly = self._to_local(mx, my, t0)
        alt = bool(mods & Qt.AltModifier)
        prop = self.lock != bool(mods & Qt.ShiftModifier)
        ax = 0.0 if alt else -hx * hw0
        ay = 0.0 if alt else -hy * hh0
        w0, h0 = 2 * hw0, 2 * hh0
        if hx:
            w = max(1.0, ((lx - ax) * hx) * (2 if alt else 1))
        else:
            w = w0
        if hy:
            h = max(1.0, ((ly - ay) * hy) * (2 if alt else 1))
        else:
            h = h0
        if prop:
            fw, fh = w / w0, h / h0
            if hx and hy:
                f = fw if abs(fw - 1) >= abs(fh - 1) else fh
            else:
                f = fw if hx else fh
            w, h = w0 * f, h0 * f
        sx = math.copysign(w / self.iw, t0.sx)
        sy = math.copysign(h / self.ih, t0.sy)
        if alt:
            clx = cly = 0.0
        else:
            clx = ax + hx * w / 2 if hx else 0.0
            cly = ay + hy * h / 2 if hy else 0.0
        rx, ry = _rot(clx, cly, t0.rot)
        return replace(t0, sx=sx, sy=sy, cx=t0.cx + rx, cy=t0.cy + ry)

    def _canvas(self, t0: Transform, ax: int, ay: int, dx: float, dy: float, mods) -> Transform:
        cw, ch = float(t0.canvas_w), float(t0.canvas_h)
        nw = max(1.0, cw + dx * ax) if ax else cw
        nh = max(1.0, ch + dy * ay) if ay else ch
        if self.lock != bool(mods & Qt.ShiftModifier):
            r = cw / ch
            if ax and ay:
                if abs(nw / cw - 1) >= abs(nh / ch - 1):
                    nh = nw / r
                else:
                    nw = nh * r
            elif ax:
                nh = nw / r
            else:
                nw = nh * r
        nw, nh = round(nw), round(nh)
        # the image stays put on screen: moving the left / top edge shifts the canvas origin
        cx, cy = t0.cx, t0.cy
        if ax < 0:
            cx += nw - cw
        elif ax == 0:
            cx += (nw - cw) / 2
        if ay < 0:
            cy += nh - ch
        elif ay == 0:
            cy += (nh - ch) / 2
        return replace(t0, canvas_w=int(nw), canvas_h=int(nh), cx=cx, cy=cy)

    def _snap(self, t: Transform, mods) -> Transform:
        """Snap the layer's edges / centre to the canvas edges / centre (hold Ctrl to move freely)."""
        self._guides = []
        if mods & Qt.ControlModifier:
            return t
        a = math.radians(t.rot)
        bw = abs(self.iw * t.sx * math.cos(a)) + abs(self.ih * t.sy * math.sin(a))
        bh = abs(self.iw * t.sx * math.sin(a)) + abs(self.ih * t.sy * math.cos(a))
        tol = 7 / self.zoom
        cx, cy = t.cx, t.cy
        for targets, size, axis in (((0, t.canvas_w / 2, t.canvas_w), bw, "x"), ((0, t.canvas_h / 2, t.canvas_h), bh, "y")):
            c = cx if axis == "x" else cy
            best = None
            for tgt in targets:
                for off in (-size / 2, 0, size / 2):
                    dlt = tgt - (c + off)
                    if abs(dlt) <= tol and (best is None or abs(dlt) < abs(best[0])):
                        best = (dlt, tgt)
            if best:
                if axis == "x":
                    cx += best[0]
                else:
                    cy += best[0]
                self._guides.append((axis, best[1]))
        return replace(t, cx=cx, cy=cy)

    # ------------------------------------------------------------ paint
    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, W, H), 12, 12)
        p.fillPath(bg, QColor(2, 7, 4, 235))
        p.setClipPath(bg)
        # faint grid
        p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.05), 1))
        for x in range(0, W, 32):
            p.drawLine(x, 0, x, H)
        for y in range(0, H, 32):
            p.drawLine(0, y, W, y)
        t = self.t
        if not t or not self.img:
            p.setPen(QColor(theme.TEXT_3))
            p.drawText(self.rect(), Qt.AlignCenter, "Pick a picture in the list to edit it")
            return
        art = QRectF(self.c2w(0, 0), self.c2w(t.canvas_w, t.canvas_h))
        # artboard: checkerboard (transparent) or the fill colour, with a soft shadow
        for i, a in enumerate((0.20, 0.12, 0.06)):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, round(255 * a)))
            p.drawRoundedRect(art.adjusted(-2 - i * 3, -2 - i * 3 + 4, 2 + i * 3, 2 + i * 3 + 4), 4 + i * 2, 4 + i * 2)
        if t.bg == "transparent":
            p.save()
            p.setClipRect(art, Qt.IntersectClip)
            p.fillRect(art, QColor(36, 44, 40))
            s = 9
            p.setBrush(QColor(24, 30, 27))
            x0, y0 = art.left(), art.top()
            yy = 0
            while y0 + yy * s < art.bottom():
                xx = yy % 2
                while x0 + xx * s < art.right():
                    p.drawRect(QRectF(x0 + xx * s, y0 + yy * s, s, s))
                    xx += 2
                yy += 1
            p.restore()
        else:
            p.fillRect(art, QColor(t.bg))

        def draw_layer(opacity):
            p.save()
            p.setOpacity(opacity)
            p.translate(self.c2w(t.cx, t.cy))
            p.rotate(t.rot)
            p.scale(self.zoom * t.sx * (-1 if t.flip_h else 1), self.zoom * t.sy * (-1 if t.flip_v else 1))
            p.drawImage(QRectF(-self.iw / 2, -self.ih / 2, self.iw, self.ih), self.img)
            p.restore()

        draw_layer(0.22)  # ghost of whatever falls outside the canvas
        p.save()
        p.setClipRect(art, Qt.IntersectClip)
        draw_layer(1.0)
        p.restore()

        # artboard outline + size label
        p.setPen(QPen(QColor(255, 255, 255, 150), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(art)
        f = QFont(theme.FONT_MONO)
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT_2))
        p.drawText(QRectF(art.left(), art.bottom() + 20, art.width(), 16), Qt.AlignHCenter | Qt.AlignTop,
                   f"{t.canvas_w} × {t.canvas_h} px")

        # snap guides
        pen = QPen(QColor("#FF4FD8"), 1)
        pen.setDashPattern([4, 3])
        p.setPen(pen)
        for axis, v in self._guides:
            if axis == "x":
                x = self.c2w(v, 0).x()
                p.drawLine(QPointF(x, 0), QPointF(x, H))
            else:
                y = self.c2w(0, v).y()
                p.drawLine(QPointF(0, y), QPointF(W, y))

        # layer bounding box, handles, rotate knob
        hw, hh = self._half()
        poly = QPolygonF([self.c2w(*self._layer_pt(x, y)) for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))])
        acc = QColor(theme.ACCENT)
        p.setPen(QPen(acc, 1.5))
        p.drawPolygon(poly)
        top = self.c2w(*self._layer_pt(0, -hh))
        knob = self._knob()
        p.drawLine(top, knob)
        hov = self._hover or ()
        p.setBrush(QColor(theme.ON_ACCENT) if hov != ("rotate",) else acc)
        p.drawEllipse(knob, 6, 6)
        for hx, hy, q in self._layer_handles():
            hot = hov == ("scale", hx, hy)
            p.setBrush(acc if hot else QColor("#FFFFFF"))
            p.setPen(QPen(acc, 1.5))
            p.drawRect(QRectF(q.x() - HANDLE, q.y() - HANDLE, 2 * HANDLE, 2 * HANDLE))
        # artboard tabs (canvas size)
        for ax, ay, q in self._canvas_tabs():
            hot = hov == ("canvas", ax, ay)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1))
            p.setBrush(QColor(theme.ACCENT) if hot else QColor(232, 240, 236))
            if ax and ay:
                p.drawEllipse(q, 4.5, 4.5)
            elif ax:
                p.drawRoundedRect(QRectF(q.x() - 3, q.y() - 11, 6, 22), 3, 3)
            else:
                p.drawRoundedRect(QRectF(q.x() - 11, q.y() - 3, 22, 6), 3, 3)

        # HUD while dragging, zoom chip always
        def chip(text, at: QPointF, strong=False):
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(text) + 16
            r = QRectF(at.x(), at.y(), w, 22)
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.5 if strong else 0.2), 1))
            p.setBrush(QColor(3, 12, 7, 230))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QColor(theme.ACCENT if strong else theme.TEXT_2))
            p.drawText(r, Qt.AlignCenter, text)

        if self._hud:
            c = self.mapFromGlobal(QCursor.pos())
            chip(self._hud, QPointF(min(W - 200, c.x() + 16), min(H - 30, c.y() + 18)), True)
        chip(f"{self.zoom * 100:.0f}%", QPointF(W - 62, H - 32))


class _Spin(QDoubleSpinBox):
    def __init__(self, lo, hi, dec, suffix, tip):
        super().__init__()
        self.setRange(lo, hi)
        self.setDecimals(dec)
        self.setSuffix(suffix)
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.setKeyboardTracking(False)
        self.setFixedHeight(32)


class ImageEditor(QWidget):
    """Editor = options bar + canvas + tool bar. Emits edited(Transform) on every user change."""

    edited = Signal(object)
    resetRequested = Signal()
    applyAllRequested = Signal()

    def __init__(self):
        super().__init__()
        self.t: Transform | None = None
        self.iw = self.ih = 1
        self.path = None
        self._undo: dict[str, list[Transform]] = {}
        self._redo: dict[str, list[Transform]] = {}
        self._syncing = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # ---- options bar (sizes)
        bar = QFrame()
        bar.setObjectName("EditorBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        b = QHBoxLayout(bar)
        b.setContentsMargins(10, 6, 10, 6)
        b.setSpacing(6)
        self.w_spin = QSpinBox()
        self.h_spin = QSpinBox()
        for sb, name in ((self.w_spin, "Width"), (self.h_spin, "Height")):
            sb.setRange(1, 30000)
            sb.setSuffix(" px")
            sb.setButtonSymbols(QSpinBox.NoButtons)
            sb.setKeyboardTracking(False)
            sb.setAccessibleName(f"Output {name.lower()}")
            sb.setToolTip(f"Output {name.lower()}: resizes the whole picture")
            sb.setFixedWidth(92)
            sb.setFixedHeight(32)
        self.chain = QPushButton()
        self.chain.setObjectName("Chain")
        self.chain.setCheckable(True)
        self.chain.setChecked(True)
        self.chain.setFixedSize(30, 30)
        self.chain.setCursor(Qt.PointingHandCursor)
        self.chain.setIconSize(QSize(16, 16))
        self.chain.toggled.connect(self._on_chain)
        self._on_chain(True)
        b.addWidget(label("W", "Faint"))
        b.addWidget(self.w_spin)
        b.addWidget(self.chain)
        b.addWidget(label("H", "Faint"))
        b.addWidget(self.h_spin)
        b.addSpacing(10)
        self.scale_spin = _Spin(1, 5000, 1, " %", "Image scale")
        self.scale_spin.setFixedWidth(84)
        self.rot_spin = _Spin(-180, 180, 1, "°", "Rotation")
        self.rot_spin.setFixedWidth(70)
        b.addWidget(label("Scale", "Faint"))
        b.addWidget(self.scale_spin)
        b.addWidget(label("Angle", "Faint"))
        b.addWidget(self.rot_spin)
        b.addStretch(1)
        self.badge = label("", "Tag")
        b.addWidget(self.badge)
        v.addWidget(bar)

        self.canvas = EditorCanvas()
        self.canvas.changed.connect(self._on_canvas)
        self.canvas.begin.connect(self._push)
        v.addWidget(self.canvas, 1)

        # ---- tool bar
        tb = QFrame()
        tb.setObjectName("EditorBar")
        tb.setAttribute(Qt.WA_StyledBackground, True)
        t = QHBoxLayout(tb)
        t.setContentsMargins(8, 5, 8, 5)
        t.setSpacing(4)
        self.btns = {}
        for key, ic, tip in (("rot_l", "rotate-ccw", "Rotate left 90°"), ("rot_r", "rotate-cw", "Rotate right 90°"),
                             ("flip_h", "flip-h", "Flip horizontally"), ("flip_v", "flip-v", "Flip vertically"),
                             ("undo", "undo", f"Undo ({theme.keys('Ctrl+Z')})")):
            btn = icon_button(ic, tip, 30, 15, "#C9D6CF")
            btn.clicked.connect(lambda _=False, k=key: self._action(k))
            self.btns[key] = btn
            t.addWidget(btn)
            if key == "flip_v":
                t.addSpacing(6)
        t.addSpacing(6)
        for key, text, tip in (("fit", "Fit", "Fit the whole picture inside the canvas"),
                               ("fill", "Fill", "Cover the canvas, cropping the overflow"),
                               ("crop", "Crop to image", "Shrink the canvas to the picture's bounds"),
                               ("reset", "Reset", "Back to the batch settings on the right")):
            btn = QPushButton(text)
            btn.setObjectName("Small")
            btn.setToolTip(tip)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._action(k))
            self.btns[key] = btn
            t.addWidget(btn)
        t.addStretch(1)
        self.bg = Segmented([("transparent", "Clear"), ("#ffffff", "White"), ("#000000", "Black")], "transparent")
        self.bg.setToolTip("Fill for empty canvas")
        self.bg.setFixedWidth(170)
        self.bg.changed.connect(self._on_bg)
        t.addWidget(self.bg)
        t.addSpacing(6)
        allb = QPushButton(" Apply to all")
        allb.setObjectName("Small")
        allb.setIcon(theme.icon("layers", "#DCE5E0", 13))
        allb.setToolTip("Use this canvas size and placement for every picture in the list")
        allb.setCursor(Qt.PointingHandCursor)
        allb.clicked.connect(self.applyAllRequested.emit)
        t.addWidget(allb)
        v.addWidget(tb)

        hint = label("Drag the picture to move it · white handles scale it · round knob rotates · tabs outside the "
                     "canvas crop or extend it · Shift / Alt modify · wheel zooms", "Faint", wrap=True)
        hint.setStyleSheet("font-size:11px;")
        v.addWidget(hint)

        self.w_spin.valueChanged.connect(lambda val: self._on_size("w", val))
        self.h_spin.valueChanged.connect(lambda val: self._on_size("h", val))
        self.scale_spin.valueChanged.connect(self._on_scale)
        self.rot_spin.valueChanged.connect(self._on_rot)
        for keys, fn in ((QKeySequence.Undo, self.undo), (QKeySequence.Redo, self.redo)):
            sc = QShortcut(keys, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        self._enable(False)

    # ------------------------------------------------------------ api
    def show_image(self, path: str | None, img: QImage | None, iw: int, ih: int, t: Transform | None, edited: bool):
        same = path == self.path
        self.path, self.iw, self.ih = path, iw, ih
        self.t = t.copy() if t else None
        self.canvas.set_image(img, iw, ih, self.t, refit=not same)
        if not same:
            self.canvas.fit_view()
        self._set_badge(edited)
        self._sync_fields()
        self._enable(t is not None)

    def set_transform(self, t: Transform, edited: bool):
        """Update from outside (batch settings changed) without recording undo."""
        self.t = t.copy()
        self.canvas.set_transform(self.t)
        self._set_badge(edited)
        self._sync_fields()

    def lock(self) -> bool:
        return self.chain.isChecked()

    # ------------------------------------------------------------ internals
    def _enable(self, on: bool):
        for w in (self.w_spin, self.h_spin, self.chain, self.scale_spin, self.rot_spin, self.bg, *self.btns.values()):
            w.setEnabled(on)

    def _set_badge(self, edited: bool):
        self.badge.setText("Custom" if edited else "Batch settings")
        self.badge.setProperty("good", edited)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)

    def _on_chain(self, on: bool):
        self.chain.setIcon(theme.icon("link" if on else "unlink", theme.ACCENT if on else theme.TEXT_3, 16))
        self.chain.setToolTip("Proportions locked (click to unlock)" if on else "Proportions unlocked (click to lock)")
        if hasattr(self, "canvas"):
            self.canvas.lock = on

    def _sync_fields(self):
        if not self.t:
            return
        self._syncing = True
        self.w_spin.setValue(int(self.t.canvas_w))
        self.h_spin.setValue(int(self.t.canvas_h))
        self.scale_spin.setValue(abs(self.t.sx) * 100)
        self.rot_spin.setValue(self.t.rot)
        self.bg.set_value(self.t.bg)
        self._syncing = False
        key = self.path or ""
        self.btns["undo"].setEnabled(bool(self._undo.get(key)))

    def _commit(self, t: Transform):
        self.t = t
        self.canvas.set_transform(t.copy())
        self._set_badge(True)
        self._sync_fields()
        self.edited.emit(t.copy())

    def _push(self):
        if self.t is None:
            return
        key = self.path or ""
        stack = self._undo.setdefault(key, [])
        stack.append(self.t.copy())
        del stack[:-60]
        self._redo[key] = []
        self.btns["undo"].setEnabled(True)

    def undo(self):
        key = self.path or ""
        if self._undo.get(key):
            self._redo.setdefault(key, []).append(self.t.copy())
            self._commit(self._undo[key].pop())

    def redo(self):
        key = self.path or ""
        if self._redo.get(key):
            self._undo.setdefault(key, []).append(self.t.copy())
            self._commit(self._redo[key].pop())

    def _on_canvas(self, t: Transform):
        self.t = t
        self._set_badge(True)
        self._sync_fields()
        self.edited.emit(t.copy())

    def _on_size(self, which: str, val: int):
        """Image-size style: W / H scale the canvas and the picture together."""
        if self._syncing or not self.t:
            return
        t = self.t
        fx = val / t.canvas_w if which == "w" else None
        fy = val / t.canvas_h if which == "h" else None
        if self.lock():
            fx = fy = fx or fy
        fx = fx or 1.0
        fy = fy or 1.0
        self._push()
        self._commit(replace(t, canvas_w=max(1, round(t.canvas_w * fx)), canvas_h=max(1, round(t.canvas_h * fy)),
                             cx=t.cx * fx, cy=t.cy * fy, sx=t.sx * fx, sy=t.sy * fy))

    def _on_scale(self, val: float):
        if self._syncing or not self.t:
            return
        s = val / 100
        t = self.t
        ratio = abs(t.sy / t.sx) if t.sx else 1.0
        self._push()
        self._commit(replace(t, sx=math.copysign(s, t.sx), sy=math.copysign(s * (1.0 if self.lock() else ratio), t.sy)))

    def _on_rot(self, val: float):
        if self._syncing or not self.t:
            return
        self._push()
        self._commit(replace(self.t, rot=val))

    def _on_bg(self, val):
        if self._syncing or not self.t:
            return
        self._push()
        self._commit(replace(self.t, bg=val))

    def _action(self, key: str):
        if key == "undo":
            self.undo()
            return
        if not self.t:
            return
        t = self.t
        if key == "reset":
            self.resetRequested.emit()
            return
        self._push()
        if key in ("rot_l", "rot_r"):
            r = ((t.rot + (-90 if key == "rot_l" else 90)) + 180) % 360 - 180
            # a quarter turn swaps the canvas sides too when the picture fills it, like Image > Rotate
            a = math.radians(t.rot)
            bw = abs(self.iw * t.sx * math.cos(a)) + abs(self.ih * t.sy * math.sin(a))
            bh = abs(self.iw * t.sx * math.sin(a)) + abs(self.ih * t.sy * math.cos(a))
            fills = abs(bw - t.canvas_w) < 2 and abs(bh - t.canvas_h) < 2
            if fills:
                t = replace(t, rot=r, canvas_w=t.canvas_h, canvas_h=t.canvas_w, cx=t.canvas_h / 2, cy=t.canvas_w / 2)
            else:
                t = replace(t, rot=r)
        elif key == "flip_h":
            t = replace(t, flip_h=not t.flip_h)
        elif key == "flip_v":
            t = replace(t, flip_v=not t.flip_v)
        elif key == "fit":
            t = fit_transform(t, self.iw, self.ih)
        elif key == "fill":
            t = fit_transform(t, self.iw, self.ih, cover=True)
        elif key == "crop":
            a = math.radians(t.rot)
            bw = abs(self.iw * t.sx * math.cos(a)) + abs(self.ih * t.sy * math.sin(a))
            bh = abs(self.iw * t.sx * math.sin(a)) + abs(self.ih * t.sy * math.cos(a))
            t = replace(t, canvas_w=max(1, round(bw)), canvas_h=max(1, round(bh)), cx=bw / 2, cy=bh / 2)
        self._commit(t)
        if key in ("rot_l", "rot_r", "crop"):
            self.canvas.fit_view()
