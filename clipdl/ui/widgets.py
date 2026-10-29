"""Small reusable widgets: segmented control, toggle, time field, flow layout, progress bar, skeleton."""
from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ..core.timefmt import fmt_time, parse_time
from . import theme


def repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def icon_button(name: str, tip: str, size: int = 34, icon_size: int = 16, color: str = "#C4CEC9",
                obj: str = "Icon") -> QPushButton:
    b = QPushButton()
    b.setObjectName(obj)
    b.setIcon(theme.icon(name, color, icon_size))
    b.setIconSize(QSize(icon_size, icon_size))
    b.setFixedSize(size, size)
    b.setToolTip(tip)
    b.setAccessibleName(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


class Card(QFrame):
    def __init__(self, name: str = "Card", parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.setAttribute(Qt.WA_StyledBackground, True)


class Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Divider")
        self.setAttribute(Qt.WA_StyledBackground, True)


# ---------------------------------------------------------------- segmented control

class Segmented(QFrame):
    """A row of mutually exclusive buttons. Values can be any hashable."""

    changed = Signal(object)

    def __init__(self, options: list[tuple[object, str]], value=None, tall: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("tall", tall)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)  # never squashed by a crowded layout
        self.setMinimumHeight(40 if tall else 38)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(3, 3, 3, 3)
        self._lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[object, QPushButton] = {}
        self._value = None
        self.set_options(options, value)

    def set_options(self, options, value=None):
        for b in self._buttons.values():
            self._group.removeButton(b)
            b.deleteLater()
        self._buttons.clear()
        for v, text in options:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, v=v: self._clicked(v))
            self._group.addButton(b)
            self._lay.addWidget(b)
            self._buttons[v] = b
        self.set_value(value if value in self._buttons else (options[0][0] if options else None))

    def _clicked(self, v):
        if v != self._value:
            self._value = v
            self.changed.emit(v)

    def set_value(self, v):
        self._value = v
        b = self._buttons.get(v)
        if b:
            self._group.setExclusive(True)
            b.setChecked(True)

    def clear_selection(self):
        self._group.setExclusive(False)
        for b in self._buttons.values():
            b.setChecked(False)
        self._group.setExclusive(True)
        self._value = None

    def value(self):
        return self._value

    def set_label(self, v, text: str):
        if v in self._buttons:
            self._buttons[v].setText(text)

    def set_option_enabled(self, v, enabled: bool):
        if v in self._buttons:
            self._buttons[v].setEnabled(enabled)

    def values(self):
        return list(self._buttons)


# ---------------------------------------------------------------- toggle switch

class Toggle(QAbstractButton):
    def __init__(self, checked: bool = False, w: int = 40, h: int = 24, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(w, h)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        on_c = QColor(theme.ACCENT)
        off_c = theme.white(0.15)
        if not self.isEnabled():
            on_c = off_c = theme.white(0.08)
        c = QColor(
            round(off_c.red() + (on_c.red() - off_c.red()) * self._pos),
            round(off_c.green() + (on_c.green() - off_c.green()) * self._pos),
            round(off_c.blue() + (on_c.blue() - off_c.blue()) * self._pos),
            round(off_c.alpha() + (on_c.alpha() - off_c.alpha()) * self._pos))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = 3 + (r.width() - 6 - d) * self._pos
        p.setBrush(QColor(theme.ON_ACCENT) if (self._pos > 0.5 and self.height() < 20) else QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, 3, d, d))
        if self.hasFocus():
            p.setPen(QPen(theme.qcolor(theme.ACCENT, 0.7), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), r.height() / 2, r.height() / 2)

    def sizeHint(self):
        return self.size()


# ---------------------------------------------------------------- time field

class TimeField(QFrame):
    """[-] 1:12.0 [+]  — emits edited(seconds) for valid input; nudge(+/-1 or 0.1 with Shift)."""

    edited = Signal(float)
    nudged = Signal(float)

    def __init__(self, label_text: str, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self.caption = label(label_text, "FieldLabel")
        outer.addWidget(self.caption)
        self.box = QFrame()
        self.box.setObjectName("FieldBox")
        self.box.setAttribute(Qt.WA_StyledBackground, True)
        self.box.setFixedHeight(40)
        row = QHBoxLayout(self.box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.minus = icon_button("minus", f"{label_text}: back 1 s (Shift: 0.1 s)", 36, 14, obj="Step")
        self.plus = icon_button("plus", f"{label_text}: forward 1 s (Shift: 0.1 s)", 36, 14, obj="Step")
        self.minus.setFixedHeight(38)
        self.plus.setFixedHeight(38)
        self.edit = QLineEdit()
        self.edit.setObjectName("TimeEdit")
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.setFixedWidth(84)
        self.edit.setAccessibleName(label_text)
        self.caption.setBuddy(self.edit)
        row.addWidget(self.minus)
        row.addWidget(self.edit)
        row.addWidget(self.plus)
        outer.addWidget(self.box)
        self._value = 0.0
        self.minus.clicked.connect(lambda: self._nudge(-1))
        self.plus.clicked.connect(lambda: self._nudge(1))
        self.edit.textEdited.connect(self._on_text)
        self.edit.editingFinished.connect(self._on_done)
        self.edit.installEventFilter(self)

    def eventFilter(self, obj, e):
        if obj is self.edit:
            if e.type() == e.Type.FocusIn:
                self.box.setProperty("focus", True)
                repolish(self.box)
            elif e.type() == e.Type.FocusOut:
                self.box.setProperty("focus", False)
                repolish(self.box)
        return False

    def _nudge(self, sign):
        from PySide6.QtWidgets import QApplication
        step = 0.1 if QApplication.keyboardModifiers() & Qt.ShiftModifier else 1.0
        self.nudged.emit(sign * step)

    def _set_invalid(self, bad: bool):
        if self.box.property("invalid") != bad:
            self.box.setProperty("invalid", bad)
            self.edit.setProperty("invalid", bad)
            repolish(self.box)
            repolish(self.edit)

    def _on_text(self, t):
        try:
            v = parse_time(t)
        except ValueError:
            self._set_invalid(True)
            return
        self._set_invalid(False)
        self.edited.emit(v)

    def _on_done(self):
        self._set_invalid(False)
        self.set_value(self._value, force=True)

    def set_value(self, v: float, force: bool = False):
        self._value = v
        if force or not self.edit.hasFocus():
            self.edit.setText(fmt_time(v, tenths=True))

    def setEnabled(self, on):  # noqa: N802
        super().setEnabled(on)


# ---------------------------------------------------------------- flow layout (chips)

class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, w):  # noqa: N802
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):  # noqa: N802
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, r, test):
        x, y, line = r.x(), r.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            nx = x + hint.width() + self._sp
            if nx - self._sp > r.right() + 1 and line > 0:
                x, y = r.x(), y + line + self._sp
                nx = x + hint.width() + self._sp
                line = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line = max(line, hint.height())
        return y + line - r.y()

    def clear(self):
        while self._items:
            it = self._items.pop()
            if it.widget():
                it.widget().deleteLater()


# ---------------------------------------------------------------- progress bar

class FancyProgress(QWidget):
    """Rounded bar with a moving sheen; striped when 'busy' (merging), sweeping when indeterminate."""

    def __init__(self, height: int = 10, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self._value = 0.0
        self._mode = "normal"  # normal | stripes | indeterminate
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_value(self, v: float):
        self._value = max(0.0, min(100.0, v))
        self.update()

    def set_mode(self, mode: str):
        self._mode = mode
        self.update()

    def _tick(self):
        if self.isVisible():
            self._phase = (self._phase + 0.012) % 1.0
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(theme.white(0.08))
        p.drawRoundedRect(r, rad, rad)
        acc = QColor(theme.ACCENT)
        clip = QPainterPath()
        clip.addRoundedRect(r, rad, rad)
        p.setClipPath(clip)
        if self._mode == "indeterminate":
            w = r.width() * 0.3
            x = -w + (r.width() + w) * self._phase
            g = QLinearGradient(x, 0, x + w, 0)
            g.setColorAt(0, theme.qcolor(theme.ACCENT, 0))
            g.setColorAt(0.5, acc)
            g.setColorAt(1, theme.qcolor(theme.ACCENT, 0))
            p.setBrush(g)
            p.drawRect(QRectF(x, 0, w, r.height()))
            return
        fw = r.width() * self._value / 100
        if fw <= 0:
            return
        fill = QRectF(0, 0, fw, r.height())
        p.setBrush(acc)
        p.drawRoundedRect(fill, rad, rad)
        p.setClipRect(fill)
        if self._mode == "stripes":
            p.setBrush(QColor(0, 0, 0, 56))
            step = 12.0
            off = self._phase * step * 2
            x = -r.height() - step + (off % (step * 2))
            while x < fw + r.height():
                path = QPainterPath()
                path.moveTo(x, r.height())
                path.lineTo(x + r.height(), 0)
                path.lineTo(x + r.height() + step / 2, 0)
                path.lineTo(x + step / 2, r.height())
                path.closeSubpath()
                p.drawPath(path)
                x += step
        else:
            sw = 120
            x = -sw + (fw + sw) * self._phase
            g = QLinearGradient(x, 0, x + sw, 0)
            g.setColorAt(0, QColor(255, 255, 255, 0))
            g.setColorAt(0.5, QColor(255, 255, 255, 105))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(g)
            p.drawRect(QRectF(x, 0, sw, r.height()))


# ---------------------------------------------------------------- loading skeleton

class Shimmer(QWidget):
    """A rounded placeholder block with a moving highlight."""

    def __init__(self, w: int | None = None, h: int = 14, radius: float = 6, parent=None):
        super().__init__(parent)
        if w:
            self.setFixedWidth(w)
        self.setFixedHeight(h)
        self._r = radius
        self._phase = 0.0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(16)

    def _tick(self):
        if self.isVisible():
            self._phase = (self._phase + 0.014) % 1.0
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        w = r.width()
        x = -w + 2 * w * self._phase
        g = QLinearGradient(x, 0, x + w, 0)
        g.setColorAt(0, theme.white(0.04))
        g.setColorAt(0.5, theme.white(0.10))
        g.setColorAt(1, theme.white(0.04))
        p.setPen(Qt.NoPen)
        p.setBrush(theme.white(0.04))
        p.drawRoundedRect(r, self._r, self._r)
        p.setBrush(g)
        p.drawRoundedRect(r, self._r, self._r)


class Dot(QWidget):
    """Small status dot; pulses when 'pulse' is on."""

    def __init__(self, color: str = theme.ACCENT, size: int = 6, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._c = QColor(color)
        self._pulse = False
        self._a = 1.0
        self._dir = -1
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)

    def set_color(self, color: str):
        self._c = QColor(color)
        self.update()

    def set_pulse(self, on: bool):
        self._pulse = on
        if on:
            self._t.start(40)
        else:
            self._t.stop()
            self._a = 1.0
        self.update()

    def _tick(self):
        self._a = max(0.35, min(1.0, self._a + self._dir * 0.05))
        if self._a <= 0.35:
            self._dir = 1
        elif self._a >= 1.0:
            self._dir = -1
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self._c)
        c.setAlphaF(self._a)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(self.rect()))
