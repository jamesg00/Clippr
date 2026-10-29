"""Preview player: QMediaPlayer -> QVideoSink -> painted surface with overlays + transport controls."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..core.timefmt import fmt_time
from . import theme
from .trim_track import SeekBar
from .widgets import Dot, icon_button, label

try:  # QtMultimedia can be missing on stripped-down installs; the app still works without preview
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
    HAVE_MM = True
except Exception:  # noqa: BLE001
    HAVE_MM = False


class VideoSurface(QWidget):
    """Paints the latest video frame (or thumbnail / placeholder) with rounded top corners."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self._img: QImage | None = None
        self._thumb: QImage | None = None
        self.message = ""

    def set_image(self, img: QImage | None):
        self._img = img
        self.update()

    def set_thumbnail(self, img: QImage | None):
        self._thumb = img
        self.update()

    def clear(self):
        self._img = None
        self._thumb = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        rad = 11
        path.moveTo(r.left(), r.bottom())
        path.lineTo(r.left(), r.top() + rad)
        path.quadTo(r.left(), r.top(), r.left() + rad, r.top())
        path.lineTo(r.right() - rad, r.top())
        path.quadTo(r.right(), r.top(), r.right(), r.top() + rad)
        path.lineTo(r.right(), r.bottom())
        path.closeSubpath()
        p.setClipPath(path)
        p.fillRect(r, QColor("#000000"))
        img = self._img if self._img is not None and not self._img.isNull() else self._thumb
        if img is not None and not img.isNull():
            s = img.size().scaled(self.size(), Qt.KeepAspectRatio)
            x = (self.width() - s.width()) / 2
            y = (self.height() - s.height()) / 2
            p.drawImage(QRectF(x, y, s.width(), s.height()), img)
            if img is self._thumb and self._img is None:
                p.fillRect(QRectF(x, y, s.width(), s.height()), QColor(0, 0, 0, 90))
        else:
            # 16:9 grid placeholder
            h = self.height()
            w = min(self.width(), h * 16 / 9)
            x0 = (self.width() - w) / 2
            p.fillRect(QRectF(x0, 0, w, h), QColor("#070A09"))
            p.setPen(QPen(theme.white(0.025), 1))
            step = 32
            xx = x0
            while xx < x0 + w:
                p.drawLine(int(xx), 0, int(xx), int(h))
                xx += step
            yy = 0
            while yy < h:
                p.drawLine(int(x0), int(yy), int(x0 + w), int(yy))
                yy += step
        if self.message:
            p.setPen(QColor(theme.TEXT_3))
            p.setFont(theme.font(11))
            p.drawText(QRectF(12, self.height() - 26, self.width() - 24, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       self.message)


class PlayerView(QFrame):
    positionChanged = Signal(float)
    playingChanged = Signal(bool)
    setStartRequested = Signal(float)
    setEndRequested = Signal(float)
    loopToggled = Signal(bool)
    fullscreenToggled = Signal()
    volumeChanged = Signal(float)
    previewFailed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PlayerFrame")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.duration = 1.0
        self.clip = (0.0, 1.0)
        self.loop = False
        self.volume = 0.8
        self._muted = False
        self._pos = 0.0
        self._playing = False
        self._scrubbing = False
        self._audio_split = False

        v = QVBoxLayout(self)
        v.setContentsMargins(1, 1, 1, 1)
        v.setSpacing(0)

        # --- surface + overlays
        self.surface = VideoSurface()
        v.addWidget(self.surface, 1)

        self.info_card = QFrame(self.surface)
        self.info_card.setStyleSheet("QFrame{background:rgba(10,13,12,0.78);border:1px solid rgba(255,255,255,0.08);"
                                     "border-radius:10px;}")
        ic = QVBoxLayout(self.info_card)
        ic.setContentsMargins(12, 9, 12, 10)
        ic.setSpacing(3)
        self.title_lbl = label("", "Title")
        self.title_lbl.setStyleSheet("background:transparent;border:none;font-size:15px;font-weight:600;")
        self.title_lbl.setWordWrap(True)
        self.channel_lbl = label("", "Muted")
        self.channel_lbl.setStyleSheet("background:transparent;border:none;font-size:12px;")
        ic.addWidget(self.title_lbl)
        ic.addWidget(self.channel_lbl)

        self.src_badge = QLabel(self.surface)
        self.src_badge.setStyleSheet(
            f"QLabel{{background:rgba(10,13,12,0.78);border:1px solid rgba(255,255,255,0.08);border-radius:6px;"
            f"padding:3px 8px;font-family:'{theme.FONT_MONO}';font-size:11px;color:#C4CEC9;}}")

        self.big_play = QPushButton(self.surface)
        self.big_play.setObjectName("BigPlay")
        self.big_play.setFixedSize(64, 64)
        self.big_play.setIcon(theme.icon("play", "#FFFFFF", 24))
        self.big_play.setIconSize(QSize(24, 24))
        self.big_play.setCursor(Qt.PointingHandCursor)
        self.big_play.setAccessibleName("Play")
        self.big_play.clicked.connect(self.toggle)

        self.playing_tag = QWidget(self.surface)
        pt = QHBoxLayout(self.playing_tag)
        pt.setContentsMargins(8, 3, 8, 3)
        pt.setSpacing(6)
        self.playing_dot = Dot()
        self.playing_dot.set_pulse(True)
        self.playing_lbl = label("Playing", "Muted")
        self.playing_lbl.setStyleSheet("font-size:11px;color:#C4CEC9;")
        pt.addWidget(self.playing_dot)
        pt.addWidget(self.playing_lbl)
        self.playing_tag.hide()

        # --- seek bar
        bottom = QFrame()
        bottom.setObjectName("Transport")
        bottom.setAttribute(Qt.WA_StyledBackground, True)
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 0, 0, 2)
        bv.setSpacing(0)
        self.seek = SeekBar()
        self.seek.seekRequested.connect(self.seek_to)
        self.seek.scrubbing.connect(self._on_scrub)
        bv.addWidget(self.seek)

        # --- transport
        row = QHBoxLayout()
        row.setContentsMargins(10, 0, 10, 4)
        row.setSpacing(4)
        self.btn_back = icon_button("skip-back", "Jump to clip start (Home)")
        self.btn_play = QPushButton()
        self.btn_play.setObjectName("PlayMain")
        self.btn_play.setFixedSize(38, 38)
        self.btn_play.setIconSize(QSize(16, 16))
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.clicked.connect(self.toggle)
        self.btn_fwd = icon_button("skip-fwd", "Jump to clip end (End)")
        self.time_lbl = QLabel()
        self.time_lbl.setTextFormat(Qt.RichText)
        self.time_lbl.setMinimumWidth(118)
        self.time_lbl.setStyleSheet(f"font-family:'{theme.FONT_MONO}';font-size:13px;padding-left:8px;")
        sep = QFrame()
        sep.setFixedSize(1, 22)
        sep.setStyleSheet("background:rgba(255,255,255,0.08);")
        self.btn_in = QPushButton("Set start   I")
        self.btn_out = QPushButton("Set end   O")
        self.btn_loop = QPushButton(" Loop clip")
        for b in (self.btn_in, self.btn_out, self.btn_loop):
            b.setObjectName("Small")
            b.setCursor(Qt.PointingHandCursor)
        self.btn_in.setToolTip("Set the clip start to the playhead (I)")
        self.btn_out.setToolTip("Set the clip end to the playhead (O)")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setChecked(False)
        self.btn_loop.setToolTip("Replay just the clip (L)")
        self._loop_icons()
        self.btn_vol = icon_button("volume", "Mute (scroll to change volume)")
        self.btn_full = icon_button("fullscreen", "Fullscreen preview (F)")
        row.addWidget(self.btn_back)
        row.addWidget(self.btn_play)
        row.addWidget(self.btn_fwd)
        row.addWidget(self.time_lbl)
        row.addWidget(sep)
        row.addSpacing(6)
        row.addWidget(self.btn_in)
        row.addWidget(self.btn_out)
        row.addWidget(self.btn_loop)
        row.addStretch(1)
        row.addWidget(self.btn_vol)
        row.addWidget(self.btn_full)
        bv.addLayout(row)
        v.addWidget(bottom)

        self.btn_back.clicked.connect(lambda: self.seek_to(self.clip[0]))
        self.btn_fwd.clicked.connect(lambda: self.seek_to(max(self.clip[0], self.clip[1] - 0.1)))
        self.btn_in.clicked.connect(lambda: self.setStartRequested.emit(self._pos))
        self.btn_out.clicked.connect(lambda: self.setEndRequested.emit(self._pos))
        self.btn_loop.toggled.connect(self._on_loop)
        self.btn_vol.clicked.connect(self._toggle_mute)
        self.btn_vol.installEventFilter(self)
        self.btn_full.clicked.connect(self.fullscreenToggled.emit)

        # --- media
        self.player = self.audio_player = None
        self.audio_out = self.audio_out2 = None
        if HAVE_MM:
            try:
                self.sink = QVideoSink(self)
                self.sink.videoFrameChanged.connect(self._on_frame)
                self.player = QMediaPlayer(self)
                self.audio_out = QAudioOutput(self)
                self.player.setAudioOutput(self.audio_out)
                self.player.setVideoOutput(self.sink)
                self.player.positionChanged.connect(self._on_pos)
                self.player.playbackStateChanged.connect(self._on_state)
                self.player.errorOccurred.connect(self._on_error)
                self.audio_player = QMediaPlayer(self)
                self.audio_out2 = QAudioOutput(self)
                self.audio_player.setAudioOutput(self.audio_out2)
            except Exception:  # noqa: BLE001
                self.player = None
        self._sync = QTimer(self)
        self._sync.setInterval(1000)
        self._sync.timeout.connect(self._resync_audio)
        self._nam = QNetworkAccessManager(self)
        self._thumb_reply = None
        self.set_volume(self.volume)
        self._refresh_play_icon()
        self._refresh_time()

    # ------------------------------------------------------------ overlays
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_overlays()

    def _place_overlays(self):
        s = self.surface
        self.info_card.setFixedWidth(min(460, int(s.width() * 0.56)))
        self.info_card.adjustSize()
        self.info_card.move(12, 12)
        self.src_badge.adjustSize()
        self.src_badge.move(s.width() - self.src_badge.width() - 12, 12)
        self.big_play.move((s.width() - 64) // 2, (s.height() - 64) // 2)
        self.playing_tag.adjustSize()
        self.playing_tag.move(s.width() - self.playing_tag.width() - 8, s.height() - self.playing_tag.height() - 6)

    def eventFilter(self, obj, e):
        if obj is self.btn_vol and e.type() == e.Type.Wheel:
            step = 0.05 if e.angleDelta().y() > 0 else -0.05
            self.set_volume(min(1.0, max(0.0, self.volume + step)))
            self.volumeChanged.emit(self.volume)
            return True
        return False

    # ------------------------------------------------------------ API
    def load(self, info, clip: tuple[float, float]):
        self.stop()
        self.duration = info.duration
        self.clip = clip
        self._pos = clip[0]
        self.title_lbl.setText(info.title)
        self.channel_lbl.setText(" · ".join(x for x in (info.channel, fmt_time(info.duration)) if x))
        badge = []
        if info.max_height:
            badge.append(f"{info.max_height}p")
        if info.fps:
            badge.append(f"{round(info.fps)} fps")
        self.src_badge.setText(" · ".join(badge) or "source")
        self.surface.clear()
        self.surface.message = ""
        self._load_thumbnail(info.thumbnail)
        self.seek.set_state(duration=self.duration, position=self._pos, start=clip[0], end=clip[1])
        self._audio_split = False
        if self.player is not None and info.preview_video is not None:
            self.player.setSource(QUrl(info.preview_video.url))
            if info.preview_audio is not None and self.audio_player is not None:
                self._audio_split = True
                self.audio_player.setSource(QUrl(info.preview_audio.url))
                self.audio_out.setMuted(True)
            else:
                self.audio_out.setMuted(self._muted)
            self.player.setPosition(int(self._pos * 1000))
            if self._audio_split:
                self.audio_player.setPosition(int(self._pos * 1000))
        elif self.player is None:
            self.surface.message = "Preview isn't available (Qt Multimedia missing). Trimming still works."
        else:
            self.surface.message = "No preview stream for this video. Trimming still works."
        self._refresh_play_icon()
        self._refresh_time()
        self._place_overlays()

    def unload(self):
        self.stop()
        if self.player is not None:
            self.player.setSource(QUrl())
            self.audio_player.setSource(QUrl())
        self.surface.clear()

    def set_clip(self, start: float, end: float):
        self.clip = (start, end)
        self.seek.set_state(start=start, end=end)

    def set_loop(self, on: bool):
        self.btn_loop.setChecked(on)

    def set_volume(self, v: float):
        self.volume = v
        for out in (self.audio_out, self.audio_out2):
            if out is not None:
                out.setVolume(v)
        self.btn_vol.setToolTip(f"Volume {round(v * 100)}% · click to mute, scroll to change")

    def position(self) -> float:
        return self._pos

    def is_playing(self) -> bool:
        return self._playing

    def toggle(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if self.player is None or self.player.source().isEmpty():
            return
        s, e = self.clip
        # Play from wherever the playhead is. Only when Loop is on and the playhead is
        # sitting at the clip's end do we restart the clip (like pressing play on a finished loop).
        if self.loop and e - 0.15 <= self._pos <= e + 0.15:
            self.seek_to(s)
        if self._pos >= self.duration - 0.1:
            self.seek_to(0)
        self.player.play()
        if self._audio_split:
            self.audio_player.setPosition(self.player.position())
            self.audio_player.play()
            self._sync.start()

    def pause(self):
        if self.player is not None:
            self.player.pause()
            if self._audio_split:
                self.audio_player.pause()
        self._sync.stop()

    def stop(self):
        if self.player is not None:
            self.player.stop()
            self.audio_player.stop()
        self._sync.stop()
        self._set_playing(False)

    def seek_to(self, t: float):
        t = max(0.0, min(self.duration, t))
        self._pos = t
        if self.player is not None:
            self.player.setPosition(int(t * 1000))
            if self._audio_split:
                self.audio_player.setPosition(int(t * 1000))
        self.seek.set_state(position=t)
        self._refresh_time()
        self.positionChanged.emit(t)

    def step(self, delta: float):
        self.seek_to(self._pos + delta)

    # ------------------------------------------------------------ internals
    def _on_frame(self, frame):
        img = frame.toImage()
        if not img.isNull():
            self.surface.set_image(img)

    def _on_pos(self, ms: int):
        if self._scrubbing:
            return
        t = ms / 1000
        s, e = self.clip
        prev = self._pos
        # Loop wraps only when playback runs off the end of the clip from inside it.
        # Anywhere outside the clip the whole video plays normally.
        if self.loop and self._playing and s - 0.05 <= prev < e and t >= e - 0.03 and t - prev < 1.5:
            self.seek_to(s)
            return
        self._pos = t
        self.seek.set_state(position=t)
        self._refresh_time()
        self.positionChanged.emit(t)

    def _on_state(self, state):
        self._set_playing(state == QMediaPlayer.PlayingState)

    def _set_playing(self, on: bool):
        if on == self._playing:
            return
        self._playing = on
        self._refresh_play_icon()
        self.playingChanged.emit(on)

    def _on_error(self, *_):
        msg = self.player.errorString() if self.player is not None else ""
        self.surface.message = "Preview stopped. Trimming and downloading still work."
        self.surface.update()
        self.previewFailed.emit(msg)

    def _on_scrub(self, on: bool):
        self._scrubbing = on

    def _resync_audio(self):
        if not self._audio_split or not self._playing:
            return
        drift = abs(self.audio_player.position() - self.player.position())
        if drift > 150:
            self.audio_player.setPosition(self.player.position())

    def _on_loop(self, on: bool):
        self.loop = on
        self._loop_icons()
        self.loopToggled.emit(on)
        self._refresh_play_icon()

    def _loop_icons(self):
        on = self.btn_loop.isChecked()
        self.btn_loop.setIcon(theme.icon("loop", theme.ACCENT if on else "#DCE5E0", 14))

    def _toggle_mute(self):
        self._muted = not self._muted
        target = self.audio_out2 if self._audio_split else self.audio_out
        if target is not None:
            target.setMuted(self._muted)
        self.btn_vol.setIcon(theme.icon("volume-x" if self._muted else "volume", "#C4CEC9", 16))

    def _refresh_play_icon(self):
        self.btn_play.setIcon(theme.icon("pause" if self._playing else "play", "#0A0D0C", 16))
        self.btn_play.setToolTip("Pause (Space)" if self._playing else "Play (Space)")
        self.btn_play.setAccessibleName("Pause" if self._playing else "Play")
        has_src = self.player is not None and not self.player.source().isEmpty()
        self.big_play.setVisible(not self._playing and has_src)
        self.playing_tag.setVisible(self._playing)
        self.info_card.setVisible(not self._playing)
        self.src_badge.setVisible(not self._playing)
        self.playing_lbl.setText("Playing · looping clip" if self.loop else "Playing")
        self._place_overlays()

    def _refresh_time(self):
        self.time_lbl.setText(f"<span style='color:{theme.TEXT}'>{fmt_time(self._pos)}</span>"
                              f"<span style='color:{theme.TEXT_3}'> / {fmt_time(self.duration)}</span>")

    def _load_thumbnail(self, url: str | None):
        if not url:
            return
        if self._thumb_reply is not None:
            self._thumb_reply.abort()
        reply = self._nam.get(QNetworkRequest(QUrl(url)))
        self._thumb_reply = reply

        def done():
            if reply.error() == QNetworkReply.NoError:
                img = QImage()
                if img.loadFromData(reply.readAll()):
                    self.surface.set_thumbnail(img)
            reply.deleteLater()
            if self._thumb_reply is reply:
                self._thumb_reply = None

        reply.finished.connect(done)
