"""Qt wrappers that run core functions on QThreadPool and report via signals."""
from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QRunnable, Signal

from ..core import clipper, local_media, media_info, waveform


class JobSignals(QObject):
    progress = Signal(object)  # clipper.Progress
    log = Signal(str)
    done = Signal(object)  # result payload
    failed = Signal(str, str)  # friendly message, detail
    cancelled = Signal()


class _Job(QRunnable):
    def __init__(self, token: str):
        super().__init__()
        self.setAutoDelete(True)
        self.token = token
        self.signals = JobSignals()
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()


class InfoJob(_Job):
    """extract_info + parse_info -> VideoInfo."""

    def __init__(self, token: str, url: str, ffmpeg: str | None, cookies: str | None = None):
        super().__init__(token)
        self.url, self.ffmpeg, self.cookies = url, ffmpeg, cookies

    def run(self):
        try:
            raw = media_info.fetch_info(self.url, self.ffmpeg, cookies=self.cookies)
            info = media_info.parse_info(raw)
            if self.cancel_event.is_set():
                return
            self.signals.done.emit((self.token, info))
        except media_info.InfoError as e:
            self.signals.failed.emit(str(e), repr(e.__cause__ or e))
        except Exception:  # noqa: BLE001
            self.signals.failed.emit("Couldn't load this video.", traceback.format_exc())


class LocalInfoJob(_Job):
    """Read a file from this computer -> VideoInfo."""

    def __init__(self, token: str, path: str, ffmpeg: str | None):
        super().__init__(token)
        self.path, self.ffmpeg = path, ffmpeg

    def run(self):
        try:
            info = local_media.probe(self.path, self.ffmpeg or "")
            if not self.cancel_event.is_set():
                self.signals.done.emit((self.token, info))
        except local_media.LocalError as e:
            self.signals.failed.emit(str(e), "")
        except Exception:  # noqa: BLE001
            self.signals.failed.emit("Couldn't open this file.", traceback.format_exc())


class WaveformJob(_Job):
    def __init__(self, token: str, ffmpeg: str, stream, duration: float):
        super().__init__(token)
        self.ffmpeg, self.stream, self.duration = ffmpeg, stream, duration

    def run(self):
        try:
            peaks = waveform.compute_peaks(self.ffmpeg, self.stream, self.duration, self.cancel_event)
        except Exception:  # noqa: BLE001 - the waveform is decoration; never fail loudly
            peaks = None
        if peaks and not self.cancel_event.is_set():
            self.signals.done.emit((self.token, peaks))


class ClipJob(_Job):
    def __init__(self, token: str, req: clipper.ClipRequest):
        super().__init__(token)
        self.req = req

    def run(self):
        c = clipper.Clipper(self.req, self.cancel_event, self.signals.progress.emit, self.signals.log.emit)
        try:
            res = c.run()
            self.signals.done.emit((self.token, res))
        except clipper.Cancelled:
            self.signals.cancelled.emit()
        except clipper.ClipError as e:
            if self.cancel_event.is_set():
                self.signals.cancelled.emit()
            else:
                self.signals.failed.emit(str(e), e.detail)
        except Exception:  # noqa: BLE001
            if self.cancel_event.is_set():
                self.signals.cancelled.emit()
            else:
                self.signals.failed.emit("Something went wrong while making the clip.", traceback.format_exc())


class FuncJob(_Job):
    """Runs fn(progress, log, cancel_event) -> result on the pool. progress(pct: float|None, text: str)."""

    def __init__(self, token: str, fn):
        super().__init__(token)
        self.fn = fn

    def run(self):
        def progress(pct, text=""):
            self.signals.progress.emit((self.token, pct, text))

        try:
            res = self.fn(progress, self.signals.log.emit, self.cancel_event)
            if self.cancel_event.is_set():
                self.signals.cancelled.emit()
            else:
                self.signals.done.emit((self.token, res))
        except clipper.Cancelled:
            self.signals.cancelled.emit()
        except clipper.ClipError as e:
            if self.cancel_event.is_set():
                self.signals.cancelled.emit()
            else:
                self.signals.failed.emit(str(e), e.detail)
        except Exception as e:  # noqa: BLE001
            if self.cancel_event.is_set():
                self.signals.cancelled.emit()
            else:
                self.signals.failed.emit(str(e) or "Something went wrong.", traceback.format_exc())
