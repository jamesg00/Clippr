"""QmlBackend: the bridge between the QML front end and Clippr's existing core/ and workers/ code.

It plays the same role as clipdl/controller.py does for the widget UI (state machine: empty -> loading -> ready ->
downloading -> done / error) but exposes plain Qt properties, signals and slots that QML binds to. Nothing in
core/ or workers/ is changed; this file only calls into them.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import Property, QObject, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

from ..core import clipper, encode, local_media, media_info, paths, settings
from ..core.timefmt import fmt_time, parse_time
from ..workers.jobs import ClipJob, InfoJob, LocalInfoJob, WaveformJob

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    HAVE_MM = True
except Exception:  # noqa: BLE001
    HAVE_MM = False

MIN_CLIP = 0.2
DEFAULT_CLIP = 30.0

THEMES = ("auto", "light", "graphite", "noir", "paper", "mint", "midnight", "ocean", "sunset", "rose")
SESSIONS = ("clip", "mp3", "convert", "resize", "compress")


class State:
    EMPTY, LOADING, READY, DOWNLOADING, DONE, ERROR = "empty", "loading", "ready", "downloading", "done", "error"


def _ytdlp_version() -> str:
    try:
        from yt_dlp.version import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return ""


class QmlBackend(QObject):
    # one change-signal per group keeps the boilerplate small; QML re-reads every property in the group
    stateChanged = Signal()
    urlChanged = Signal()
    videoChanged = Signal()
    rangeChanged = Signal()
    positionUpdated = Signal()
    playingChanged = Signal()
    outputChanged = Signal()
    jobChanged = Signal()
    statusChanged = Signal()
    appearanceChanged = Signal()
    peaksChanged = Signal()
    resultChanged = Signal()
    errorChanged = Signal()
    sessionChanged = Signal()
    toast = Signal(str)  # transient message for QML

    def __init__(self, cfg: settings.AppSettings, settings_path: Path | None = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.settings_path = settings_path
        self.pool = QThreadPool.globalInstance()
        self.ffmpeg = paths.ffmpeg_path()
        self._ytdlp = _ytdlp_version()

        # --- state
        self._state = State.EMPTY
        self._session = (cfg.tools.get("_app") or {}).get("session", "clip")
        if self._session not in SESSIONS:
            self._session = "clip"
        self._url_text = ""
        self._url_error = ""
        self.info: media_info.VideoInfo | None = None
        self.url: str | None = None
        self._local = False  # the loaded video is a file from this computer
        self.token = 0
        self._start = 0.0
        self._end = 0.0
        self._pos = 0.0
        self._playing = False
        self._loop = cfg.loop
        self._volume = cfg.volume
        self._muted = False
        self._peaks: list[float] = []
        self._file_name = ""
        self._out = replace(cfg.output)
        self._precise = cfg.precise
        self._folder = cfg.save_folder
        self._status = ""
        self._status_kind = "idle"
        self._progress: clipper.Progress | None = None
        self._job_title = ""
        self._job_sub = ""
        self._cancelling = False
        self._result: clipper.ClipResult | None = None
        self._error_title = ""
        self._error_msg = ""
        self._error_detail = ""
        self.job: ClipJob | None = None
        self.info_job: InfoJob | None = None
        self.wave_job: WaveformJob | None = None
        self._audio_split = False
        self._scrubbing = False

        # --- appearance (cfg.appearance / cfg.opacity already exist; theme + blur live under cfg.tools["_ui"])
        ui = cfg.tools.get("_ui") or {}
        self._theme = ui.get("theme") if ui.get("theme") in THEMES else "mint"
        mode = cfg.appearance or "frosted"
        frost = ui.get("frost")
        self._blur = int(frost) if isinstance(frost, (int, float)) and 0 <= frost <= 100 else (0 if mode == "clear" else 60)
        self._reduce = bool(ui.get("reduceMotion", False))
        self._mode = "solid" if mode == "solid" else "glass"
        self._opacity = round(min(1.0, max(0.15, cfg.opacity)) / 0.05) * 0.05

        # --- media
        self.player = self.audio_player = self.audio_out = self.audio_out2 = None
        if HAVE_MM:
            try:
                self.player = QMediaPlayer(self)
                self.audio_out = QAudioOutput(self)
                self.player.setAudioOutput(self.audio_out)
                self.player.positionChanged.connect(self._on_player_pos)
                self.player.playbackStateChanged.connect(self._on_player_state)
                self.player.errorOccurred.connect(self._on_player_error)
                self.audio_player = QMediaPlayer(self)
                self.audio_out2 = QAudioOutput(self)
                self.audio_player.setAudioOutput(self.audio_out2)
            except Exception:  # noqa: BLE001
                self.player = None
        self._sync = QTimer(self)
        self._sync.setInterval(1000)
        self._sync.timeout.connect(self._resync_audio)
        self._apply_volume()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.saveSettings)
        self._refresh_status()

    # ================================================================= helpers
    def _emit_range(self):
        self.rangeChanged.emit()
        self.outputChanged.emit()  # the size estimate depends on the clip length

    def _set_state(self, s: str):
        self._state = s
        self.stateChanged.emit()
        self._refresh_status()

    def _status_set(self, text: str, kind: str = "idle"):
        self._status, self._status_kind = text, kind
        self.statusChanged.emit()

    def _refresh_status(self):
        s = self._state
        if not self.ffmpeg and s in (State.EMPTY, State.READY):
            self._status_set("ffmpeg wasn't found. Put ffmpeg.exe in the app's bin folder or on PATH, then restart.",
                             "error")
        elif s == State.EMPTY:
            self._status_set("Paste a YouTube, Instagram or X link to get started.", "idle")
        elif s == State.LOADING:
            self._status_set("Loading video…", "busy")
        elif s == State.READY:
            verb = "Playing" if self._playing else "Paused at"
            self._status_set(f"{verb} {fmt_time(self._pos)}  ·  Clip {fmt_time(self._start, True)} → "
                             f"{fmt_time(self._end, True)} ({fmt_time(self._end - self._start, True)})",
                             "busy" if self._playing else "ok")
        elif s == State.DOWNLOADING:
            p = self._progress
            if p is None or p.phase == "preparing":
                self._status_set("Finding the best streams…", "busy")
            elif p.phase == "finishing":
                self._status_set("Finishing up…", "busy")
            else:
                spd = f"  ·  {p.speed_x:.1f}× realtime" if p.speed_x else ""
                self._status_set(f"Downloading {fmt_time(self._start, True)} → {fmt_time(self._end, True)}  ·  "
                                 f"{int(p.percent)}%{spd}", "busy")
        elif s == State.DONE and self._result:
            self._status_set(f"Saved to {self._result.path}", "ok")
        elif s == State.ERROR:
            self._status_set(self._error_msg, "error")

    def _save_soon(self):
        self._save_timer.start()

    @Slot()
    def saveSettings(self):
        self.cfg.output = replace(self._out)
        self.cfg.precise = self._precise
        if self._folder:
            self.cfg.save_folder = self._folder
        self.cfg.loop = self._loop
        self.cfg.volume = self._volume
        self.cfg.appearance = "solid" if self._mode == "solid" else ("frosted" if self._blur > 0 else "clear")
        self.cfg.opacity = float(min(1.0, max(0.15, self._opacity)))
        self.cfg.tools["_ui"] = {"theme": self._theme, "frost": self._blur, "reduceMotion": self._reduce}
        self.cfg.tools["_app"] = {"session": self._session}
        settings.save(self.cfg, self.settings_path)

    # ================================================================= read-only facts
    @Property(str, constant=True)
    def fontUi(self) -> str:
        from ..ui import theme
        return theme.FONT_UI

    @Property(str, constant=True)
    def fontMono(self) -> str:
        from ..ui import theme
        return theme.FONT_MONO

    @Property(str, constant=True)
    def platform(self) -> str:
        from ..ui import glass
        return glass.platform_kind()

    @Property(bool, constant=True)
    def hasMultimedia(self) -> bool:
        return self.player is not None

    @Property(bool, constant=True)
    def ffmpegOk(self) -> bool:
        return bool(self.ffmpeg)

    @Property(str, constant=True)
    def ytdlpVersion(self) -> str:
        return self._ytdlp

    @Property("QStringList", constant=True)
    def themeIds(self):
        return list(THEMES)

    # ================================================================= session
    @Property(str, notify=sessionChanged)
    def session(self) -> str:
        return self._session

    @Slot(str)
    def setSession(self, key: str):
        if key in SESSIONS or key == "appearance":
            self._session = key
            self.sessionChanged.emit()
            if key in SESSIONS:
                self._save_soon()

    @Slot(str)
    def openClassic(self, key: str):
        """Tool sessions are not rebuilt in QML yet: open them in the classic window for now."""
        root = paths.app_root()
        args = [sys.executable, str(root / "run.py"), "--session", key]
        try:
            subprocess.Popen(args, cwd=str(root))
        except OSError:
            self.toast.emit("Couldn't open the classic window.")

    # ================================================================= state / url
    @Property(str, notify=stateChanged)
    def state(self) -> str:
        return self._state

    @Property(str, notify=urlChanged)
    def urlText(self) -> str:
        return self._url_text

    @Property(str, notify=urlChanged)
    def urlError(self) -> str:
        return self._url_error

    @Slot(str)
    def setUrlText(self, t: str):
        self._url_text = t
        if self._url_error:
            self._url_error = ""
        self.urlChanged.emit()

    @Slot()
    def pasteAndLoad(self):
        text = (QGuiApplication.clipboard().text() or "").strip()
        if not text:
            self._status_set("The clipboard is empty. Copy a video link first.", "error")
            return
        self.loadUrl(text)

    @Slot(str)
    def loadUrl(self, text: str):
        if self._state == State.DOWNLOADING:
            return
        self._url_text = text
        clean, had_list = media_info.clean_url(text)
        if not clean:
            self._url_error = "That isn't a YouTube, Instagram or X video link."
            self.urlChanged.emit()
            self._status_set(self._url_error, "error")
            return
        self._url_error = ""
        self.urlChanged.emit()
        self._cancel_aux_jobs()
        self._unload_player()
        self.info = None
        self._local = False
        self.url = clean
        self.token += 1
        self._set_state(State.LOADING)
        if had_list:
            self.toast.emit("Playlist link: loading just this video.")
        job = InfoJob(str(self.token), clean, self.ffmpeg, self.cfg.cookies)
        job.signals.done.connect(self._on_info)
        job.signals.failed.connect(self._on_info_failed)
        self.info_job = job
        self.pool.start(job)

    @Slot(str)
    def loadFile(self, where: str):
        """Open a video/audio file from this computer (a path or a file:// url) to clip a part of it."""
        if self._state in (State.DOWNLOADING, State.LOADING):
            return
        path = QUrl(where).toLocalFile() if where.startswith("file:") else where
        if not path or not local_media.is_media(path):
            self._status_set("That isn't a video or audio file.", "error")
            self.toast.emit("That isn't a video or audio file.")
            return
        self._url_text = path
        self._url_error = ""
        self.urlChanged.emit()
        self._cancel_aux_jobs()
        self._unload_player()
        self.info = None
        self._local = True
        self.url = path
        self.token += 1
        self._set_state(State.LOADING)
        job = LocalInfoJob(str(self.token), path, self.ffmpeg)
        job.signals.done.connect(self._on_info)
        job.signals.failed.connect(self._on_info_failed)
        self.info_job = job
        self.pool.start(job)

    @Slot()
    def browseFile(self):
        if self._state in (State.DOWNLOADING, State.LOADING):
            return
        from PySide6.QtWidgets import QFileDialog
        exts = " ".join("*" + e for e in sorted(local_media.MEDIA_EXTS))
        f, _ = QFileDialog.getOpenFileName(None, "Open a video or audio file", str(Path.home()),
                                           f"Video and audio ({exts});;All files (*)")
        if f:
            self.loadFile(f)

    @Slot()
    def clear(self):
        if self._state == State.DOWNLOADING:
            return
        self._cancel_aux_jobs()
        self.token += 1
        self._unload_player()
        self.info = None
        self.url = None
        self._url_text = ""
        self._url_error = ""
        self._peaks = []
        self.urlChanged.emit()
        self.peaksChanged.emit()
        self.videoChanged.emit()
        self._set_state(State.EMPTY)

    def _on_info(self, payload):
        token, info = payload
        if token != str(self.token):
            return
        self.info_job = None
        self.info = info
        t0 = 0.0
        try:
            t = None if self._local else (parse_qs(urlparse(self.url).query).get("t") or [None])[0]
            if t:
                t0 = float(str(t).rstrip("s"))
        except ValueError:
            t0 = 0.0
        t0 = min(max(0.0, t0), max(0.0, info.duration - MIN_CLIP))
        self._start = t0
        self._end = min(info.duration, t0 + DEFAULT_CLIP)
        self._peaks = []
        self._file_name = encode.sanitize_filename(info.title + ("_clip" if self._local else ""))
        self._load_player(info)
        self.videoChanged.emit()
        self.peaksChanged.emit()
        self._emit_range()
        self._set_state(State.READY)
        if info.waveform_audio and self.ffmpeg:
            wj = WaveformJob(str(self.token), self.ffmpeg, info.waveform_audio, info.duration)
            wj.signals.done.connect(self._on_waveform)
            self.wave_job = wj
            self.pool.start(wj)

    def _on_info_failed(self, msg: str, detail: str):
        self.info_job = None
        self.info = None
        self._url_error = msg
        self.urlChanged.emit()
        self.videoChanged.emit()
        self._set_state(State.EMPTY)
        self._status_set(msg, "error")

    def _on_waveform(self, payload):
        token, peaks = payload
        if token == str(self.token):
            self._peaks = [float(x) for x in peaks]
            self.peaksChanged.emit()

    def _cancel_aux_jobs(self):
        for j in (self.info_job, self.wave_job):
            if j is not None:
                j.cancel()
        self.info_job = self.wave_job = None

    # ================================================================= video facts for QML
    @Property(str, notify=videoChanged)
    def title(self) -> str:
        return self.info.title if self.info else ""

    @Property(str, notify=videoChanged)
    def channel(self) -> str:
        if not self.info:
            return ""
        return " · ".join(x for x in (self.info.channel, fmt_time(self.info.duration)) if x)

    @Property(str, notify=videoChanged)
    def thumbnail(self) -> str:
        return (self.info.thumbnail or "") if self.info else ""

    @Property(float, notify=videoChanged)
    def duration(self) -> float:
        return float(self.info.duration) if self.info else 0.0

    @Property(str, notify=videoChanged)
    def sourceBadge(self) -> str:
        if not self.info:
            return ""
        parts = []
        if self.info.max_height:
            parts.append(f"{self.info.max_height}p")
        if self.info.fps:
            parts.append(f"{round(self.info.fps)} fps")
        return " · ".join(parts) or "source"

    @Property(bool, notify=videoChanged)
    def hasPreview(self) -> bool:
        return bool(self.player is not None and self.info and self.info.preview_video is not None)

    @Property("QVariantList", notify=videoChanged)
    def audioTracks(self):
        if not self.info or not self.info.audio_tracks:
            return []
        return [{"value": t[0], "label": t[1]} for t in self.info.audio_tracks]

    @Property(str, notify=videoChanged)
    def audioLang(self) -> str:
        return (self.info.audio_lang or "") if self.info else ""

    @Slot(str)
    def setAudioTrack(self, lang: str):
        info = self.info
        if info is None or lang == info.audio_lang:
            return
        from ..core.media_info import pick_preview
        info.audio_lang = lang
        pv, pa = pick_preview(info.formats, lang)
        if pv is not None:
            pos = self._pos
            info.preview_video, info.preview_audio = pv, pa
            self._load_player(info)
            self.seek(pos)
        self.videoChanged.emit()
        name = next((t[1] for t in info.audio_tracks if t[0] == lang), lang)
        self.toast.emit(f"Audio: {name}")

    @Property("QVariantList", notify=peaksChanged)
    def peaks(self):
        return self._peaks

    # ================================================================= trim range
    @Property(float, notify=rangeChanged)
    def startSec(self) -> float:
        return self._start

    @Property(float, notify=rangeChanged)
    def endSec(self) -> float:
        return self._end

    @Property(float, notify=positionUpdated)
    def positionSec(self) -> float:
        return self._pos

    @Slot(float, result=str)
    def fmt(self, sec: float) -> str:
        return fmt_time(sec)

    @Slot(float, result=str)
    def fmtTenths(self, sec: float) -> str:
        return fmt_time(sec, True)

    def _can_trim(self) -> bool:
        return self.info is not None and self._state != State.DOWNLOADING

    @Slot(float)
    def setStart(self, t: float):
        if not self._can_trim():
            return
        self._start = round(max(0.0, min(t, self._end - MIN_CLIP)), 2)
        self._range_touched()

    @Slot(float)
    def setEnd(self, t: float):
        if not self._can_trim():
            return
        self._end = round(min(self.info.duration, max(t, self._start + MIN_CLIP)), 2)
        self._range_touched()

    @Slot(float, float)
    def setRange(self, s: float, e: float):
        """Called while a trim handle (or the whole clip) is dragged."""
        if not self._can_trim():
            return
        dur = self.info.duration
        s = max(0.0, min(s, dur - MIN_CLIP))
        e = min(dur, max(e, s + MIN_CLIP))
        moved_start = abs(s - self._start) > 1e-6
        moved_end = abs(e - self._end) > 1e-6
        self._start, self._end = round(s, 2), round(e, 2)
        self._range_touched()
        if not self._playing:  # paused: show the frame under the handle being dragged
            if moved_end and not moved_start:
                self.seek(max(self._start, self._end - 0.05))
            elif moved_start:
                self.seek(self._start)

    @Slot(str)
    def setStartText(self, text: str):
        try:
            self.setStart(parse_time(text))
        except ValueError:
            pass
        self.rangeChanged.emit()  # re-sync the field text either way

    @Slot(str)
    def setEndText(self, text: str):
        try:
            self.setEnd(parse_time(text))
        except ValueError:
            pass
        self.rangeChanged.emit()

    @Slot(float)
    def nudgeStart(self, d: float):
        self.setStart(self._start + d)

    @Slot(float)
    def nudgeEnd(self, d: float):
        self.setEnd(self._end + d)

    @Slot()
    def markStart(self):
        self.setStart(round(self._pos, 1))

    @Slot()
    def markEnd(self):
        self.setEnd(round(self._pos, 1))

    def _range_touched(self):
        if self._state == State.DONE:
            self._set_state(State.READY)
        self._emit_range()
        self._refresh_status()

    # ================================================================= player
    def _load_player(self, info):
        self._unload_player()
        self._pos = self._start
        self._audio_split = False
        if self.player is not None and info.preview_video is not None:
            self.player.setSource(self._media_url(info.preview_video.url))
            if info.preview_audio is not None and self.audio_player is not None:
                self._audio_split = True
                self.audio_player.setSource(QUrl(info.preview_audio.url))
                self.audio_out.setMuted(True)
            else:
                self.audio_out.setMuted(self._muted)
            self.player.setPosition(int(self._pos * 1000))
            if self._audio_split:
                self.audio_player.setPosition(int(self._pos * 1000))
        self.positionUpdated.emit()

    @staticmethod
    def _media_url(u: str) -> QUrl:
        return QUrl(u) if u.startswith(("http:", "https:")) else QUrl.fromLocalFile(u)

    def _unload_player(self):
        self._stop_player()
        if self.player is not None:
            self.player.setSource(QUrl())
            self.audio_player.setSource(QUrl())
        self._pos = 0.0
        self.positionUpdated.emit()

    @Slot(QObject)
    def attachVideoSink(self, sink):
        """QML hands over its VideoOutput.videoSink so frames go straight to the GPU scene graph."""
        if self.player is not None and sink is not None:
            self.player.setVideoSink(sink)

    @Property(bool, notify=playingChanged)
    def playing(self) -> bool:
        return self._playing

    @Property(bool, notify=playingChanged)
    def loopClip(self) -> bool:
        return self._loop

    @Property(float, notify=playingChanged)
    def volume(self) -> float:
        return self._volume

    @Property(bool, notify=playingChanged)
    def muted(self) -> bool:
        return self._muted

    @Slot()
    def togglePlay(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    @Slot()
    def play(self):
        if self.player is None or self.player.source().isEmpty():
            return
        s, e = self._start, self._end
        # like a DAW: playing starts at the in-marker unless the playhead was parked inside the clip
        if self._pos < s - 0.02 or self._pos >= e - 0.05:
            self.seek(s)
        self.player.play()
        if self._audio_split:
            self.audio_player.setPosition(self.player.position())
            self.audio_player.play()
            self._sync.start()

    @Slot()
    def pause(self):
        if self.player is not None:
            self.player.pause()
            if self._audio_split:
                self.audio_player.pause()
        self._sync.stop()

    def _stop_player(self):
        if self.player is not None:
            self.player.stop()
            self.audio_player.stop()
        self._sync.stop()
        self._set_playing(False)

    @Slot(float)
    def seek(self, t: float):
        if self.info is None:
            return
        t = max(0.0, min(self.info.duration, t))
        self._pos = t
        if self.player is not None:
            self.player.setPosition(int(t * 1000))
            if self._audio_split:
                self.audio_player.setPosition(int(t * 1000))
        self.positionUpdated.emit()

    @Slot(float)
    def step(self, delta: float):
        self.seek(self._pos + delta)

    @Slot(bool)
    def setScrubbing(self, on: bool):
        self._scrubbing = on

    @Slot()
    def toggleLoop(self):
        self._loop = not self._loop
        self.playingChanged.emit()
        self._save_soon()

    @Slot(float)
    def setVolume(self, v: float):
        self._volume = min(1.0, max(0.0, v))
        if self._volume > 0 and self._muted:
            self._muted = False
            self._apply_mute()
        self._apply_volume()
        self.playingChanged.emit()
        self._save_soon()

    @Slot()
    def toggleMute(self):
        self._muted = not self._muted
        self._apply_mute()
        self.playingChanged.emit()

    def _apply_volume(self):
        for out in (self.audio_out, self.audio_out2):
            if out is not None:
                out.setVolume(self._volume)

    def _apply_mute(self):
        target = self.audio_out2 if self._audio_split else self.audio_out
        if target is not None:
            target.setMuted(self._muted)

    def _on_player_pos(self, ms: int):
        if self._scrubbing:
            return
        t = ms / 1000
        s, e = self._start, self._end
        prev = self._pos
        if self._playing and s - 0.05 <= prev < e and t >= e - 0.03 and t - prev < 1.5:
            self.seek(s)  # reached the out-marker: loop back, or stop on the in-marker
            if not self._loop:
                self.pause()
            return
        self._pos = t
        self.positionUpdated.emit()
        if self._state == State.READY and self._playing:
            self._refresh_status()

    def _on_player_state(self, state):
        self._set_playing(state == QMediaPlayer.PlayingState)

    def _set_playing(self, on: bool):
        if on == self._playing:
            return
        self._playing = on
        self.playingChanged.emit()
        self._refresh_status()

    def _on_player_error(self, *_):
        self.toast.emit("Preview stopped. Trimming and downloading still work.")

    def _resync_audio(self):
        if not self._audio_split or not self._playing:
            return
        if abs(self.audio_player.position() - self.player.position()) > 150:
            self.audio_player.setPosition(self.player.position())

    # ================================================================= output settings
    def _norm(self):
        return encode.normalize(self._out)

    @Property(str, notify=outputChanged)
    def fmtValue(self) -> str:
        return self._out.format

    @Property(str, notify=outputChanged)
    def resValue(self) -> str:
        return str(self._out.resolution)

    @Property(str, notify=outputChanged)
    def fpsValue(self) -> str:
        return str(self._out.fps)

    @Property(str, notify=outputChanged)
    def codecValue(self) -> str:
        return self._norm().codec

    @Property(int, notify=outputChanged)
    def quality(self) -> int:
        return int(self._out.quality)

    @Property(bool, notify=outputChanged)
    def audioOn(self) -> bool:
        return bool(self._norm().audio)

    @Property(int, notify=outputChanged)
    def audioBitrate(self) -> int:
        return int(self._out.audio_bitrate)

    @Property(bool, notify=outputChanged)
    def precise(self) -> bool:
        return self._precise

    @Property(bool, notify=outputChanged)
    def isVideoFormat(self) -> bool:
        return self._out.format != "mp3"

    @Property(bool, notify=outputChanged)
    def isGif(self) -> bool:
        return self._out.format == "gif"

    @Property("QVariantList", constant=True)
    def formatChoices(self):
        return [{"value": v, "label": l, "enabled": True} for v, l in
                (("mp4", "MP4"), ("webm", "WebM"), ("mov", "MOV"), ("gif", "GIF"), ("mp3", "MP3"))]

    @Property("QVariantList", notify=videoChanged)
    def resolutionChoices(self):
        src = self.info.max_height if self.info else None
        out = [{"value": "src", "label": "Source", "enabled": True}]
        for h in (1080, 720, 480, 360):
            out.append({"value": str(h), "label": f"{h}p", "enabled": not src or h <= src})
        return out

    @Property("QVariantList", constant=True)
    def fpsChoices(self):
        return [{"value": "src", "label": "Source", "enabled": True}] + \
               [{"value": str(f), "label": str(f), "enabled": True} for f in (60, 30, 24, 15)]

    @Property("QVariantList", notify=outputChanged)
    def codecChoices(self):
        fmt = self._out.format
        return [{"value": v, "label": l, "enabled": encode.codec_allowed(fmt, v) or v == self._norm().codec}
                for v, l in (("h264", "H.264"), ("h265", "H.265"), ("vp9", "VP9"))]

    @Property("QVariantList", constant=True)
    def bitrateChoices(self):
        return [{"value": str(b), "label": f"{b}k", "enabled": True} for b in settings.AUDIO_BITRATES]

    @Slot(str, str)
    def setOutput(self, key: str, value: str):
        o = self._out
        if key == "format" and value in settings.FORMATS:
            o.format = value
        elif key == "resolution":
            o.resolution = "src" if value == "src" else int(value)
        elif key == "fps":
            o.fps = "src" if value == "src" else int(value)
        elif key == "codec" and value in settings.CODECS:
            if encode.codec_allowed(o.format, value):
                o.codec = value
        elif key == "audioBitrate":
            o.audio_bitrate = int(value)
        elif key == "aspect" and value in settings.ASPECTS:
            if o.aspect != value:
                o.crop_x = o.crop_y = 0.5  # a new shape starts centred
            o.aspect = value
        self._out_changed()

    @Slot(float, float)
    def setCropPos(self, x: float, y: float):
        """Where the size-preset crop box sits (0..1 along the axis the video has spare room on)."""
        self._out.crop_x = float(min(1.0, max(0.0, x)))
        self._out.crop_y = float(min(1.0, max(0.0, y)))
        self._out_changed()

    @Property(float, notify=outputChanged)
    def cropX(self) -> float:
        return float(getattr(self._out, "crop_x", 0.5))

    @Property(float, notify=outputChanged)
    def cropY(self) -> float:
        return float(getattr(self._out, "crop_y", 0.5))

    @Slot(int)
    def setQuality(self, q: int):
        self._out.quality = int(min(100, max(10, round(q / 5) * 5)))
        self._out_changed()

    @Slot(bool)
    def setAudioOn(self, on: bool):
        self._out.audio = bool(on)
        self._out_changed()

    @Slot(bool)
    def setPrecise(self, on: bool):
        self._precise = bool(on)
        self._out_changed()

    def _out_changed(self):
        if self._state == State.DONE:
            self._set_state(State.READY)
        self.outputChanged.emit()
        self._save_soon()

    @Property(str, notify=outputChanged)
    def fileName(self) -> str:
        return self._file_name

    @Slot(str)
    def setFileName(self, n: str):
        self._file_name = n
        self.outputChanged.emit()

    @Property(str, notify=outputChanged)
    def extension(self) -> str:
        return encode.EXT[self._out.format]

    @Property(str, notify=outputChanged)
    def folder(self) -> str:
        return self._folder

    @Slot()
    def browse(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(None, "Save clips to", self._folder or str(paths.default_download_dir()))
        if d:
            self._folder = os.path.normpath(d)
            self.outputChanged.emit()
            self._save_soon()

    @Property(str, notify=outputChanged)
    def estimateText(self) -> str:
        if not self.info:
            return ""
        length = max(0.0, self._end - self._start)
        mb = encode.estimate_size_mb(self._out, length, self.info.max_height, self.info.fps)
        size = f"{mb * 1000:.0f} KB" if mb < 1 else f"{mb:.1f} MB"
        return f"≈ {size} · {fmt_time(length, True)}"

    @Property(str, notify=outputChanged)
    def encodeTag(self) -> str:
        if not self.info:
            return ""
        copy = not encode.needs_reencode(self._out, self._precise, None, self.info.max_height, self.info.fps)
        return "Stream copy" if copy else "Re-encode"

    @Property(str, notify=outputChanged)
    def aspectValue(self) -> str:
        return getattr(self._out, "aspect", "src")

    @Property(str, notify=outputChanged)
    def summaryText(self) -> str:
        if not self.info:
            return ""
        return " · ".join(encode.summary_parts(self._out, self.info.max_height, self.info.fps)[:4])

    # ================================================================= download
    @Property(bool, notify=stateChanged)
    def canDownload(self) -> bool:
        return self.info is not None and self._state == State.READY and bool(self.ffmpeg)

    @Slot()
    def download(self):
        if self._state != State.READY or self.info is None:
            return
        if not self.ffmpeg:
            self._show_error("ffmpeg is missing", "Put ffmpeg.exe in the app's bin folder or on PATH, then restart.")
            return
        folder = self._folder or str(paths.default_download_dir())
        name = encode.sanitize_filename(self._file_name, encode.sanitize_filename(self.info.title))
        req = clipper.ClipRequest(url=self.url, start=self._start, end=self._end, output=encode.normalize(self._out),
                                  precise=self._precise, folder=folder, filename=name, ffmpeg=self.ffmpeg,
                                  src_height=self.info.max_height, src_fps=self.info.fps, cookies=self.cfg.cookies,
                                  audio_lang=self.info.audio_lang,
                                  local_stream=self.info.preview_video or self.info.waveform_audio if self._local else None)
        self.pause()
        self._progress = None
        self._cancelling = False
        job = ClipJob(clipper.new_job_id(), req)
        job.signals.progress.connect(self._on_progress)
        job.signals.done.connect(self._on_done)
        job.signals.failed.connect(self._on_failed)
        job.signals.cancelled.connect(self._on_cancelled)
        self.job = job
        o = req.output
        self._job_title = f"{name}.{encode.EXT[o.format]}"
        self._job_sub = f"{fmt_time(self._start, True)} → {fmt_time(self._end, True)} · " + \
                        " · ".join(encode.summary_parts(o, req.src_height, req.src_fps)[:3])
        self._set_state(State.DOWNLOADING)
        self.jobChanged.emit()
        self.pool.start(job)

    @Property(float, notify=jobChanged)
    def progress(self) -> float:
        """0..1 overall progress; negative while the amount is not known yet."""
        p = self._progress
        if p is None or p.phase == "preparing" or p.indeterminate:
            return -1.0
        return min(1.0, p.percent / 100.0)

    @Property(str, notify=jobChanged)
    def jobTitle(self) -> str:
        return self._job_title

    @Property(str, notify=jobChanged)
    def jobSub(self) -> str:
        return self._job_sub

    @Property(str, notify=jobChanged)
    def jobPhase(self) -> str:
        if self._cancelling:
            return "Cancelling…"
        p = self._progress
        if p is None or p.phase == "preparing":
            return "Finding the best streams…"
        return {"downloading": "Downloading", "encoding": "Encoding", "finishing": "Finishing up…"}.get(p.phase, p.phase)

    @Property(str, notify=jobChanged)
    def jobDetail(self) -> str:
        p = self._progress
        if p is None:
            return ""
        bits = []
        if p.speed_x:
            bits.append(f"{p.speed_x:.1f}× realtime")
        if p.net_bytes_per_s:
            bits.append(f"{p.net_bytes_per_s / 1_000_000:.1f} MB/s")
        if p.eta_s is not None:
            bits.append(f"{fmt_time(p.eta_s)} left")
        return " · ".join(bits)

    def _on_progress(self, p):
        if self._state != State.DOWNLOADING:
            return
        self._progress = p
        self.jobChanged.emit()
        self._refresh_status()

    def _on_done(self, payload):
        _, res = payload
        self.job = None
        self._result = res
        self._set_state(State.DONE)
        self.resultChanged.emit()

    def _on_failed(self, msg: str, detail: str):
        self.job = None
        self._show_error("Couldn't make the clip", msg, detail)

    def _show_error(self, title, msg, detail=""):
        self._error_title, self._error_msg, self._error_detail = title, msg, detail
        self.errorChanged.emit()
        self._set_state(State.ERROR)

    def _on_cancelled(self):
        self.job = None
        self._cancelling = False
        self._set_state(State.READY)
        self.toast.emit("Download cancelled. Nothing was saved.")

    @Slot()
    def cancel(self):
        if self.job is not None:
            self.job.cancel()
            self._cancelling = True
            self.jobChanged.emit()

    @Slot()
    def retry(self):
        if self.info is not None:
            self._set_state(State.READY)
            self.download()

    @Slot()
    def backToReady(self):
        self._set_state(State.READY if self.info is not None else State.EMPTY)

    # result / error text
    @Property(str, notify=resultChanged)
    def resultName(self) -> str:
        return Path(self._result.path).name if self._result else ""

    @Property(str, notify=resultChanged)
    def resultMeta(self) -> str:
        r = self._result
        if not r:
            return ""
        bits = [f"{r.size_bytes / 1_000_000:.1f} MB", fmt_time(self._end - self._start, True)]
        bits += r.summary[:3]
        if r.stream_copy:
            bits.append("copy")
        return " · ".join(bits)

    @Property(str, notify=resultChanged)
    def resultElapsed(self) -> str:
        return f"Done in {fmt_time(self._result.elapsed_s)}" if self._result else ""

    @Property(str, notify=errorChanged)
    def errorTitle(self) -> str:
        return self._error_title

    @Property(str, notify=errorChanged)
    def errorMessage(self) -> str:
        return self._error_msg

    @Slot()
    def showInFolder(self):
        if self._result:
            paths.reveal(self._result.path)

    @Slot()
    def openSaveFolder(self):
        folder = self._folder or str(paths.default_download_dir())
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ================================================================= status line
    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status

    @Property(str, notify=statusChanged)
    def statusKind(self) -> str:
        return self._status_kind

    # ================================================================= appearance
    @Property(str, notify=appearanceChanged)
    def themeId(self) -> str:
        return self._theme

    @Property(str, notify=appearanceChanged)
    def mode(self) -> str:
        return self._mode

    @Property(float, notify=appearanceChanged)
    def opacity(self) -> float:
        return self._opacity

    @Property(int, notify=appearanceChanged)
    def frost(self) -> int:
        return self._blur

    @Property(bool, notify=appearanceChanged)
    def reduceMotion(self) -> bool:
        return self._reduce

    @Slot(str)
    def setTheme(self, t: str):
        if t in THEMES:
            self._theme = t
            self.appearanceChanged.emit()
            self._save_soon()

    @Slot(str)
    def setMode(self, m: str):
        if m in ("solid", "glass", "frosted", "clear"):
            self._mode = "solid" if m == "solid" else "glass"
            self.appearanceChanged.emit()
            self._save_soon()

    @Slot(float)
    def setOpacity(self, v: float):
        self._opacity = float(min(1.0, max(0.15, v)))
        self.appearanceChanged.emit()
        self._save_soon()

    @Slot(int)
    def setFrost(self, v: int):
        self._blur = int(min(100, max(0, v)))
        self.appearanceChanged.emit()
        self._save_soon()

    @Slot(bool)
    def setReduceMotion(self, on: bool):
        self._reduce = bool(on)
        self.appearanceChanged.emit()
        self._save_soon()

    # ================================================================= window glue
    @Slot(QObject, str, int, str, float, result=str)
    def applyGlass(self, window, mode: str, frost: int, color: str, opacity: float) -> str:
        """Ask the OS for the see-through backdrop. Returns what is actually in effect.

        solid: opaque window. glass: frost 0 is sharp see-through, above 0 the desktop is blurred and tinted with `color`.
        """
        from ..ui import glass
        try:
            if mode == "solid":
                glass.forget_frost(window)
                return glass.apply(window, "solid")
            c = color.lstrip("#")
            rgb = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)) if len(c) >= 6 else (16, 16, 18)
            return glass.apply_frost(window, frost, rgb, opacity)
        except Exception:  # noqa: BLE001
            return "solid"

    @Slot(result=bool)
    def requestClose(self) -> bool:
        """True when the window may close. QML shows its own confirm sheet while a clip is downloading."""
        return self.job is None

    @Slot()
    def shutdown(self):
        if self.job is not None:
            self.job.cancel()
        self._cancel_aux_jobs()
        self._stop_player()
        self.saveSettings()
        self.pool.waitForDone(4000)
