"""A desktop snapshot for the Frost slider (Windows).

Windows' own acrylic has one fixed blur strength. To let the Frost slider choose how blurred the desktop behind the
window is, the app takes a picture of the monitor the window is on (without the window itself in it), shows it
behind the interface and blurs it in QML. The picture is refreshed every few seconds and after the window moves.

The window is only hidden from screen capture for a few milliseconds while the picture is taken, and never
otherwise, so screenshots and recordings of the app work normally. If anything here fails the app falls back to
Windows' built-in acrylic.
"""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import Property, QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickImageProvider

WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11


class SnapshotProvider(QQuickImageProvider):
    """Serves the latest snapshot to QML as image://desktop/<n>."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.image = QImage(2, 2, QImage.Format.Format_RGB32)
        self.image.fill(QColor("#101012"))

    def requestImage(self, id, size, requestedSize):  # noqa: A002, N802
        return self.image


def _capture_monitor(hwnd: int, downscale: bool = True) -> tuple[QImage, tuple[int, int, int, int]]:
    """Grab the monitor under `hwnd` with that window left out. Returns (image, (left, top, width, height))."""
    import ctypes
    from ctypes import wintypes

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = ctypes.c_void_p
    user32.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, wintypes.UINT]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    hmon = user32.MonitorFromWindow(wintypes.HWND(hwnd), 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not hmon or not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        raise OSError("no monitor")
    left, top = mi.rcMonitor.left, mi.rcMonitor.top
    w, h = mi.rcMonitor.right - left, mi.rcMonitor.bottom - top
    if w <= 0 or h <= 0:
        raise OSError("empty monitor")

    if not user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE):
        raise OSError("window can't be left out of the capture")
    hdc = mem = bmp = old = None
    try:
        time.sleep(0.07)  # let the desktop compositor drop the window from capture
        hdc = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        old = gdi32.SelectObject(mem, bmp)
        if not gdi32.BitBlt(mem, 0, 0, w, h, hdc, left, top, 0x00CC0020 | 0x40000000):  # SRCCOPY | CAPTUREBLT
            raise OSError("BitBlt failed")
        bih = BITMAPINFOHEADER()
        bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bih.biWidth, bih.biHeight, bih.biPlanes, bih.biBitCount = w, -h, 1, 32
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bih), 0):
            raise OSError("GetDIBits failed")
        data = bytes(buf)
    finally:
        user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), WDA_NONE)  # always give the window back to captures
        if mem and old:
            gdi32.SelectObject(mem, old)
        if bmp:
            gdi32.DeleteObject(bmp)
        if mem:
            gdi32.DeleteDC(mem)
        if hdc:
            user32.ReleaseDC(None, hdc)
    img = QImage(data, w, h, w * 4, QImage.Format.Format_RGB32).copy()
    if downscale and w * h > 2_500_000:  # keep the texture small; it is blurred anyway
        img = img.scaled(w // 2, h // 2, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return img, (left, top, w, h)


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, hwnd: int):
        super().__init__()
        self.setAutoDelete(True)
        self.hwnd = hwnd
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.done.emit(_capture_monitor(self.hwnd))
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(str(e))


class DesktopBlur(QObject):
    snapChanged = Signal()
    failedChanged = Signal()

    def __init__(self, provider: SnapshotProvider, parent=None):
        super().__init__(parent)
        self._provider = provider
        self._id = 0
        self._busy = False
        self._failures = 0
        self._failed = False
        self._available = False
        if sys.platform == "win32":
            try:
                self._available = sys.getwindowsversion().build >= 19041  # WDA_EXCLUDEFROMCAPTURE needs 2004
            except Exception:  # noqa: BLE001
                self._available = False
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    @Property(bool, constant=True)
    def available(self) -> bool:
        return self._available

    @Property(bool, notify=failedChanged)
    def failed(self) -> bool:
        return self._failed

    @Property(int, notify=snapChanged)
    def snapId(self) -> int:
        return self._id

    @Slot(QObject)
    def refresh(self, window):
        if not self._available or self._failed or self._busy or window is None:
            return
        try:
            hwnd = int(window.winId())
        except Exception:  # noqa: BLE001
            return
        self._busy = True
        job = _Job(hwnd)
        job.signals.done.connect(self._on_done)
        job.signals.failed.connect(self._on_failed)
        self._pool.start(job)

    def set_image(self, img: QImage):
        """Used by tests to inject a picture."""
        self._provider.image = img
        self._id += 1
        self.snapChanged.emit()

    def _on_done(self, payload):
        img, _rect = payload
        self._busy = False
        self._failures = 0
        self.set_image(img)

    def _on_failed(self, msg: str):
        self._busy = False
        self._failures += 1
        if self._failures >= 3:  # give up and let the app use Windows' built-in acrylic instead
            self._failed = True
            self.failedChanged.emit()
