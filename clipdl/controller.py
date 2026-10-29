"""AppController: the state machine. Widgets send actions here and redraw from what it sets."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QFileDialog, QMessageBox

from .core import clipper, encode, media_info, paths, settings
from .core.timefmt import fmt_time
from .ui import theme
from .workers.jobs import ClipJob, InfoJob, WaveformJob

MIN_CLIP = 0.2
DEFAULT_CLIP = 30.0


class State:
    EMPTY, LOADING, READY, DOWNLOADING, DONE, ERROR = "empty", "loading", "ready", "downloading", "done", "error"


def _ytdlp_version() -> str | None:
    try:
        from yt_dlp.version import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return None


class AppController(QObject):
    def __init__(self, win, cfg: settings.AppSettings, settings_path: Path | None = None):
        super().__init__(win)
        self.w = win
        self.cfg = cfg
        self.settings_path = settings_path
        self.pool = QThreadPool.globalInstance()
        self.ffmpeg = paths.ffmpeg_path()
        self.state = State.EMPTY
        self.info: media_info.VideoInfo | None = None
        self.url: str | None = None
        self.token = 0
        self.start = 0.0
        self.end = 0.0
        self.job: ClipJob | None = None
        self.info_job: InfoJob | None = None
        self.wave_job: WaveformJob | None = None
        self.last_result: clipper.ClipResult | None = None
        self._last_progress = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_settings)

        self._wire()
        self._shortcuts()
        self.w.export.load_settings(cfg.output, cfg.precise, cfg.save_folder)
        self.w.player.set_volume(cfg.volume)
        self.w.player.set_loop(cfg.loop)
        self.w.status.set_tools(_ytdlp_version(), self.ffmpeg, paths.ffmpeg_source())
        self.set_state(State.EMPTY)

    # ------------------------------------------------------------ wiring
    def _wire(self):
        w = self.w
        w.url_bar.loadRequested.connect(self.load_url)
        w.url_bar.pasteRequested.connect(self.paste_and_load)
        w.linkDropped.connect(self._on_link_dropped)
        w.url_bar.cleared.connect(self.clear)
        w.empty_view.pasteRequested.connect(self.paste_and_load)

        w.trim.rangeChanged.connect(self._on_trim_range)
        w.start_field.edited.connect(lambda t: self._set_start(t, from_field=True))
        w.end_field.edited.connect(lambda t: self._set_end(t, from_field=True))
        w.start_field.nudged.connect(lambda d: self._set_start(self.start + d))
        w.end_field.nudged.connect(lambda d: self._set_end(self.end + d))

        p = w.player
        p.positionChanged.connect(self._on_player_pos)
        p.playingChanged.connect(lambda _: self._refresh_status())
        p.setStartRequested.connect(lambda t: self._set_start(round(t, 1)))
        p.setEndRequested.connect(lambda t: self._set_end(round(t, 1)))
        p.loopToggled.connect(self._on_loop)
        p.fullscreenToggled.connect(w.toggle_fullscreen_preview)
        p.volumeChanged.connect(self._on_volume)

        e = w.export
        e.changed.connect(self._on_export_changed)
        e.downloadRequested.connect(self.download)
        e.browseRequested.connect(self.browse)
        e.audioTrackChanged.connect(self._on_audio_track)

        w.progress.cancelRequested.connect(self.cancel)
        w.done.showInFolder.connect(self.show_in_folder)
        w.done.again.connect(lambda: self.set_state(State.READY))
        w.error.retry.connect(self._retry)
        w.error.back.connect(self._error_back)

    def _shortcuts(self):
        w = self.w

        def sc(keys, fn, when=None):
            # these only apply while the Clip Video session is showing
            s = QShortcut(QKeySequence(keys), w)
            s.activated.connect(lambda: w.current_session() == "clip" and (when is None or when()) and fn())
            return s

        ready = lambda: self.state in (State.READY, State.DONE) and self.info is not None  # noqa: E731
        # one Ctrl+V for the whole window, routed to whichever session is showing
        paste = QShortcut(QKeySequence.Paste, w)
        paste.activated.connect(self._on_paste_key)
        sc("Space", self.w.player.toggle, ready)
        sc("I", lambda: self._set_start(round(self.w.player.position(), 1)), ready)
        sc("O", lambda: self._set_end(round(self.w.player.position(), 1)), ready)
        sc("L", lambda: self.w.player.set_loop(not self.w.player.loop), ready)
        sc("Home", lambda: self.w.player.seek_to(self.start), ready)
        sc("End", lambda: self.w.player.seek_to(max(self.start, self.end - 0.1)), ready)
        sc("Left", lambda: self.w.player.step(-5), ready)
        sc("Right", lambda: self.w.player.step(5), ready)
        sc("Shift+Left", lambda: self.w.player.step(-1 / 30), ready)
        sc("Shift+Right", lambda: self.w.player.step(1 / 30), ready)
        sc("F", self.w.toggle_fullscreen_preview, ready)
        sc("Escape", lambda: self.w.set_fullscreen_preview(False), self.w.is_fullscreen_preview)
        sc("Ctrl+Return", self.download, lambda: self.state == State.READY)
        sc("Ctrl+Enter", self.download, lambda: self.state == State.READY)
        sc("Ctrl+Shift+O", self.open_save_folder)

    # ------------------------------------------------------------ state
    def set_state(self, s: str):
        self.state = s
        w = self.w
        has_video = self.info is not None
        if s == State.EMPTY:
            w.left.setCurrentWidget(w.empty_view)
        elif s == State.LOADING:
            w.left.setCurrentWidget(w.loading_view)
        else:
            w.left.setCurrentWidget(w.video_page if has_video else w.empty_view)

        busy = s == State.DOWNLOADING
        w.url_bar.set_busy(busy or s == State.LOADING)
        w.trim.set_locked(busy)
        if not busy:
            w.trim.set_sweep(None)
        for f in (w.start_field, w.end_field):
            f.setEnabled(not busy and has_video)
        w.player.btn_in.setEnabled(not busy)
        w.player.btn_out.setEnabled(not busy)
        w.trim_hint.setText("Locked while downloading" if busy else
                            "Drag the handles, type times, or use Set start / Set end while playing")

        side = {State.DOWNLOADING: w.progress, State.DONE: w.done, State.ERROR: w.error}.get(s, w.export)
        w.side_stack.setCurrentWidget(side)
        w.side.setProperty("busy", s in (State.DOWNLOADING, State.DONE))
        w.side.style().unpolish(w.side)
        w.side.style().polish(w.side)
        w.export.setEnabled(has_video and s in (State.READY, State.DONE, State.ERROR))
        w.export.set_can_download(has_video and s == State.READY and bool(self.ffmpeg))
        self._refresh_status()

    def _refresh_status(self):
        st = self.w.status
        s = self.state
        if not self.ffmpeg and s in (State.EMPTY, State.READY):
            st.set_status("ffmpeg wasn't found. Put ffmpeg.exe in the app's bin folder or on PATH, then restart.",
                          theme.DANGER)
            return
        if s == State.EMPTY:
            st.set_status("Paste a YouTube, Instagram or X link to get started.", theme.TEXT_4)
        elif s == State.LOADING:
            st.set_status("Loading video…", theme.ACCENT, True)
        elif s == State.READY:
            pos = self.w.player.position()
            verb = "Playing" if self.w.player.is_playing() else "Paused at"
            st.set_status(f"{verb} {fmt_time(pos)}  ·  Clip {fmt_time(self.start, True)} → "
                          f"{fmt_time(self.end, True)} ({fmt_time(self.end - self.start, True)})",
                          theme.ACCENT, self.w.player.is_playing())
        elif s == State.DOWNLOADING:
            p = self._last_progress
            if p is None or p.phase == "preparing":
                st.set_status("Finding the best streams…", theme.ACCENT, True)
            elif p.phase == "finishing":
                st.set_status("Finishing up…", theme.ACCENT, True)
            else:
                spd = f"  ·  {p.speed_x:.1f}× realtime" if p.speed_x else ""
                st.set_status(f"Downloading {fmt_time(self.start, True)} → {fmt_time(self.end, True)}  ·  "
                              f"{int(p.percent)}%{spd}", theme.ACCENT, True)
        elif s == State.DONE and self.last_result:
            st.set_status(f"Saved to {self.last_result.path}", theme.ACCENT)
        elif s == State.ERROR:
            st.set_status(self.w.error.msg.text(), theme.DANGER)

    # ------------------------------------------------------------ loading
    def _on_paste_key(self):
        w = self.w
        if w.current_session() == "clip":
            if self.state != State.DOWNLOADING:
                self.paste_and_load()
            return
        page = w.pages.currentWidget()
        if hasattr(page, "paste_shortcut"):
            page.paste_shortcut()

    def _on_link_dropped(self, link: str):
        if self.state != State.DOWNLOADING:
            self.w.url_bar.set_text(link)
            self.load_url(link)

    def paste_and_load(self):
        text = (QGuiApplication.clipboard().text() or "").strip()
        if not text:
            self.w.status.set_status("The clipboard is empty. Copy a video link first.", theme.DANGER)
            return
        self.w.url_bar.set_text(text)
        self.load_url(text)

    def load_url(self, text: str):
        if self.state == State.DOWNLOADING:
            return
        clean, had_list = media_info.clean_url(text)
        if not clean:
            msg = "That isn't a YouTube, Instagram or X video link."
            self.w.url_bar.set_invalid(True, msg)
            if self.info is None:
                self.w.empty_view.set_error(msg)
            self.w.status.set_status(msg, theme.DANGER)
            return
        self.w.url_bar.set_invalid(False)
        self.w.empty_view.set_error(None)
        self._cancel_aux_jobs()
        self.w.player.unload()
        self.info = None
        self.url = clean
        self.token += 1
        self.set_state(State.LOADING)
        if had_list:
            QTimer.singleShot(0, lambda: self.w.status.set_status(
                "Playlist link: loading just this video.", theme.ACCENT, True))
        job = InfoJob(str(self.token), clean, self.ffmpeg, self.cfg.cookies)
        job.signals.done.connect(self._on_info)
        job.signals.failed.connect(self._on_info_failed)
        self.info_job = job
        self.pool.start(job)

    def _on_info(self, payload):
        token, info = payload
        if token != str(self.token):
            return
        self.info_job = None
        self.info = info
        t0 = 0.0
        try:
            t = (parse_qs(urlparse(self.url).query).get("t") or [None])[0]
            if t:
                t0 = float(str(t).rstrip("s"))
        except ValueError:
            t0 = 0.0
        t0 = min(max(0.0, t0), max(0.0, info.duration - MIN_CLIP))
        self.start = t0
        self.end = min(info.duration, t0 + DEFAULT_CLIP)
        w = self.w
        w.export.set_file_name(encode.sanitize_filename(info.title))
        w.export.set_source(info.max_height, info.fps, info.heights)
        w.trim.set_duration(info.duration)
        w.trim.set_peaks(None)
        w.ruler.set_duration(info.duration)
        w.export.set_audio_tracks(info.audio_tracks, info.audio_lang)
        w.player.load(info, (self.start, self.end))
        self._sync_range()
        self.set_state(State.READY)
        if info.waveform_audio and self.ffmpeg:
            wj = WaveformJob(str(self.token), self.ffmpeg, info.waveform_audio, info.duration)
            wj.signals.done.connect(self._on_waveform)
            self.wave_job = wj
            self.pool.start(wj)

    def _on_audio_track(self, lang):
        """The user picked another audio language: use it for the preview and the download."""
        info = self.info
        if info is None or lang == info.audio_lang:
            return
        from .core.media_info import pick_preview
        info.audio_lang = lang
        pv, pa = pick_preview(info.formats, lang)
        if pv is not None:
            pos = self.w.player.position()
            info.preview_video, info.preview_audio = pv, pa
            self.w.player.load(info, (self.start, self.end))
            self.w.player.seek_to(pos)
        name = next((t[1] for t in info.audio_tracks if t[0] == lang), lang)
        self.w.status.set_status(f"Audio: {name}", theme.ACCENT)

    def _on_info_failed(self, msg: str, detail: str):
        self.info_job = None
        self.info = None
        self.w.empty_view.set_error(msg)
        self.w.url_bar.set_invalid(True, msg)
        self.set_state(State.EMPTY)
        self.w.status.set_status(msg, theme.DANGER)

    def _on_waveform(self, payload):
        token, peaks = payload
        if token == str(self.token):
            self.w.trim.set_peaks(peaks)

    def _cancel_aux_jobs(self):
        for j in (self.info_job, self.wave_job):
            if j is not None:
                j.cancel()
        self.info_job = self.wave_job = None

    def clear(self):
        if self.state == State.DOWNLOADING:
            return
        self._cancel_aux_jobs()
        self.token += 1
        self.w.player.unload()
        self.info = None
        self.url = None
        self.w.empty_view.set_error(None)
        self.w.url_bar.set_invalid(False)
        self.set_state(State.EMPTY)

    # ------------------------------------------------------------ range
    def _set_start(self, t: float, from_field: bool = False):
        if self.info is None or self.state == State.DOWNLOADING:
            return
        t = max(0.0, min(t, self.end - MIN_CLIP))
        self.start = round(t, 2)
        self._sync_range(skip_field="start" if from_field else None)

    def _set_end(self, t: float, from_field: bool = False):
        if self.info is None or self.state == State.DOWNLOADING:
            return
        t = min(self.info.duration, max(t, self.start + MIN_CLIP))
        self.end = round(t, 2)
        self._sync_range(skip_field="end" if from_field else None)

    def _on_trim_range(self, s, e):
        moved_start = abs(s - self.start) > 1e-6
        moved_end = abs(e - self.end) > 1e-6
        self.start, self.end = s, e
        self._sync_range()
        # paused: show the frame under the handle being dragged
        if not self.w.player.is_playing():
            if moved_start and not moved_end:
                self.w.player.seek_to(s)
            elif moved_end and not moved_start:
                self.w.player.seek_to(max(s, e - 0.05))
            elif moved_start and moved_end:
                self.w.player.seek_to(s)

    def _sync_range(self, skip_field: str | None = None):
        w = self.w
        w.trim.set_range(self.start, self.end)
        if skip_field != "start":
            w.start_field.set_value(self.start, force=True)
        if skip_field != "end":
            w.end_field.set_value(self.end, force=True)
        w.player.set_clip(self.start, self.end)
        length = self.end - self.start
        w.clip_pill.setText(f"Clip&nbsp;&nbsp;<span style=\"font-family:'{theme.FONT_MONO}';font-weight:600;"
                            f"color:{theme.ACCENT};font-size:13px\">{fmt_time(length, True)}</span>")
        w.export.set_clip_len(length)
        if self.state == State.DONE:
            self.set_state(State.READY)
        self._refresh_status()

    def _on_player_pos(self, t: float):
        self.w.trim.set_playhead(t)
        if self.state == State.READY:
            self._refresh_status()

    # ------------------------------------------------------------ settings
    def _on_export_changed(self):
        e = self.w.export
        self.cfg.output = e.output()
        self.cfg.precise = e.precise()
        if e.folder():
            self.cfg.save_folder = e.folder()
        if self.state == State.DONE:
            self.set_state(State.READY)
        self._save_timer.start()

    def _on_loop(self, on: bool):
        self.cfg.loop = on
        self._save_timer.start()

    def _on_volume(self, v: float):
        self.cfg.volume = v
        self._save_timer.start()

    def save_settings(self):
        g = self.w.normalGeometry() if hasattr(self.w, "normalGeometry") else self.w.geometry()
        if not self.w.isMaximized() and not self.w.isFullScreen():
            self.cfg.window = [g.x(), g.y(), g.width(), g.height()]
        settings.save(self.cfg, self.settings_path)

    def browse(self):
        d = QFileDialog.getExistingDirectory(self.w, "Save clips to", self.w.export.folder() or
                                             str(paths.default_download_dir()))
        if d:
            self.w.export.set_folder(os.path.normpath(d))

    # ------------------------------------------------------------ download
    def download(self):
        if self.state != State.READY or self.info is None:
            return
        if not self.ffmpeg:
            self._show_error("ffmpeg is missing", "Put ffmpeg.exe in the app's bin folder or on PATH, then restart.")
            return
        e = self.w.export
        folder = e.folder() or str(paths.default_download_dir())
        name = encode.sanitize_filename(e.file_name(), encode.sanitize_filename(self.info.title))
        req = clipper.ClipRequest(url=self.url, start=self.start, end=self.end, output=e.output(),
                                  precise=e.precise(), folder=folder, filename=name, ffmpeg=self.ffmpeg,
                                  src_height=self.info.max_height, src_fps=self.info.fps, cookies=self.cfg.cookies,
                                  audio_lang=self.info.audio_lang)
        self.w.player.pause()
        self._last_progress = None
        self.token_dl = clipper.new_job_id()
        job = ClipJob(self.token_dl, req)
        job.signals.progress.connect(self._on_progress)
        job.signals.log.connect(self.w.progress.append_log)
        job.signals.done.connect(self._on_done)
        job.signals.failed.connect(self._on_failed)
        job.signals.cancelled.connect(self._on_cancelled)
        self.job = job
        o = req.output
        self.w.progress.start(f"{name}.{encode.EXT[o.format]}",
                              f"{fmt_time(self.start, True)} → {fmt_time(self.end, True)} · " +
                              " · ".join(encode.summary_parts(o, req.src_height, req.src_fps)[:3]))
        self.set_state(State.DOWNLOADING)
        self.pool.start(job)

    def _on_progress(self, p):
        if self.state != State.DOWNLOADING:
            return
        self._last_progress = p
        self.w.progress.update_progress(p)
        frac = None if p.phase == "preparing" else min(1.0, p.percent / 100)
        self.w.trim.set_sweep(frac)
        self._refresh_status()

    def _on_done(self, payload):
        _, res = payload
        self.job = None
        self.last_result = res
        size = f"{res.size_bytes / 1_000_000:.1f} MB"
        fmt = " · ".join(res.summary[:3]) + (" · copy" if res.stream_copy else "")
        self.set_state(State.DONE)
        self.w.done.set_result(Path(res.path).name, size, fmt_time(self.end - self.start, True), fmt,
                               fmt_time(res.elapsed_s))

    def _on_failed(self, msg: str, detail: str):
        self.job = None
        self._show_error("Couldn't make the clip", msg, detail)

    def _show_error(self, title, msg, detail=""):
        self.w.error.set_error(title, msg, detail)
        self.set_state(State.ERROR)

    def _on_cancelled(self):
        self.job = None
        self.set_state(State.READY)
        self.w.status.set_status("Download cancelled. Nothing was saved.", theme.TEXT_3)

    def cancel(self):
        if self.job is not None:
            self.job.cancel()
            self.w.progress.set_cancelling()

    def _retry(self):
        if self.info is not None:
            self.set_state(State.READY)
            self.download()

    def _error_back(self):
        self.set_state(State.READY if self.info is not None else State.EMPTY)

    # ------------------------------------------------------------ files
    def show_in_folder(self):
        if not self.last_result:
            return
        paths.reveal(self.last_result.path)

    def open_save_folder(self):
        folder = self.w.export.folder() or str(paths.default_download_dir())
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ------------------------------------------------------------ close
    def on_close(self, event) -> bool:
        """Return True if the window may close."""
        if self.job is not None:
            box = QMessageBox(self.w)
            box.setWindowTitle("Clippr")
            box.setText("A clip is still downloading. Quit and cancel it?")
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                return False
            self.job.cancel()
        self._cancel_aux_jobs()
        self.w.player.stop()
        self.save_settings()
        self.pool.waitForDone(4000)  # lets the job delete its temp folder
        return True
