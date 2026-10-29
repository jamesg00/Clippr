"""Export panel: File / Output tabs, size estimate, Download button."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLineEdit, QPushButton, QSlider, QStackedWidget, QVBoxLayout,
                               QWidget)

from ..core import encode
from ..core.settings import OutputSettings
from . import theme
from .widgets import Divider, FlowLayout, Segmented, Toggle, label, repolish

FORMAT_OPTS = [("mp4", "MP4"), ("webm", "WebM"), ("mov", "MOV"), ("gif", "GIF"), ("mp3", "MP3")]
RES_OPTS = [("src", "Source"), (1080, "1080p"), (720, "720p"), (480, "480p"), (360, "360p")]
FPS_OPTS = [("src", "Source"), (60, "60"), (30, "30"), (24, "24"), (15, "15")]
CODEC_OPTS = [("h264", "H.264"), ("h265", "H.265"), ("vp9", "VP9")]
ABR_OPTS = [(128, "128k"), (192, "192k"), (320, "320k")]


class FocusWatcher(QObject):
    """Highlights a wrapper frame while its line edit has focus."""

    def __init__(self, box: QFrame, parent=None):
        super().__init__(parent)
        self.box = box

    def eventFilter(self, obj, e):  # noqa: N802
        if e.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.box.setProperty("focus", e.type() == QEvent.FocusIn)
            repolish(self.box)
        return False


def _group(title: str, widget: QWidget, note: QWidget | None = None) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)
    head = QHBoxLayout()
    head.setContentsMargins(0, 0, 0, 0)
    head.addWidget(label(title, "FieldLabel"))
    head.addStretch(1)
    if note is not None:
        head.addWidget(note)
    v.addLayout(head)
    v.addWidget(widget)
    return w


class ExportPanel(QWidget):
    changed = Signal()  # any setting changed
    downloadRequested = Signal()
    browseRequested = Signal()
    audioTrackChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.src_height: int | None = None
        self.src_fps: float | None = None
        self.clip_len = 0.0
        self._out = OutputSettings()
        self._precise = True
        self._loading = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        self.tabs = Segmented([("file", "File"), ("output", "Output")], "file", tall=True)
        self.tabs.changed.connect(self._on_tab)
        v.addWidget(self.tabs)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_file_page())
        self.pages.addWidget(self._build_output_page())
        v.addWidget(self.pages)
        v.addStretch(1)

        # estimate row
        est = QFrame()
        est.setObjectName("Well")
        est.setAttribute(Qt.WA_StyledBackground, True)
        er = QHBoxLayout(est)
        er.setContentsMargins(12, 9, 12, 9)
        self.est_lbl = label("")
        self.est_lbl.setTextFormat(Qt.RichText)
        self.encode_tag = label("", "Tag")
        er.addWidget(self.est_lbl)
        er.addStretch(1)
        er.addWidget(self.encode_tag)
        v.addWidget(est)

        self.download_btn = QPushButton("  Download clip")
        self.download_btn.setObjectName("Primary")
        self.download_btn.setProperty("pill", True)
        self.download_btn.setIcon(theme.icon("download", theme.ON_ACCENT, 18, 2.2))
        self.download_btn.setIconSize(QSize(18, 18))
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.setToolTip(f"Download clip ({theme.keys('Ctrl+Enter')})")
        self.download_btn.clicked.connect(self.downloadRequested.emit)
        v.addWidget(self.download_btn)
        self.summary_lbl = label("", "MonoFaint")
        self.summary_lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(self.summary_lbl)

    # ------------------------------------------------------------ pages
    def _build_file_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        name_box = QFrame()
        name_box.setObjectName("FieldBox")
        name_box.setAttribute(Qt.WA_StyledBackground, True)
        name_box.setFixedHeight(40)
        nb = QHBoxLayout(name_box)
        nb.setContentsMargins(12, 0, 12, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("Bare")
        self.name_edit.setAccessibleName("File name")
        self.ext_lbl = label(".mp4", "MonoFaint")
        nb.addWidget(self.name_edit, 1)
        nb.addWidget(self.ext_lbl)
        self._focus_frame(self.name_edit, name_box)
        v.addWidget(_group("File name", name_box))

        folder_row = QWidget()
        fr = QHBoxLayout(folder_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(8)
        self.folder_edit = QLineEdit()
        self.folder_edit.setAccessibleName("Save to folder")
        self.folder_edit.addAction(theme.icon("folder", theme.TEXT_3, 15), QLineEdit.LeadingPosition)
        self.folder_edit.setStyleSheet(f"font-family:'{theme.FONT_MONO}';font-size:12px;")
        browse = QPushButton("Browse")
        browse.setCursor(Qt.PointingHandCursor)
        browse.setMinimumHeight(40)
        browse.clicked.connect(self.browseRequested.emit)
        fr.addWidget(self.folder_edit, 1)
        fr.addWidget(browse)
        v.addWidget(_group("Save to", folder_row))

        self.cut_seg = Segmented([(False, "Fast"), (True, "Frame-accurate")], True, tall=True)
        self.cut_seg.changed.connect(self._on_cut)
        cut = QWidget()
        cv = QVBoxLayout(cut)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)
        cv.addWidget(self.cut_seg)
        self.cut_help = label("", "Faint", wrap=True)
        self.cut_help.setStyleSheet("font-size:12px;")
        cv.addWidget(self.cut_help)
        v.addWidget(_group("Cut mode", cut))

        v.addWidget(Divider())
        head = QHBoxLayout()
        head.addWidget(label("Output", "FieldLabel"))
        head.addStretch(1)
        change = QPushButton("Change")
        change.setObjectName("Link")
        change.setCursor(Qt.PointingHandCursor)
        change.clicked.connect(lambda: self.set_tab("output"))
        head.addWidget(change)
        v.addLayout(head)
        chips_w = QWidget()
        self.chips = FlowLayout(chips_w, spacing=6)
        self.chip_labels = [label("", "Chip") for _ in range(6)]
        for c in self.chip_labels:
            self.chips.addWidget(c)
            c.hide()
        self.chips_w = chips_w
        v.addWidget(chips_w)

        self.name_edit.textEdited.connect(lambda _: self.changed.emit())
        self.folder_edit.textEdited.connect(lambda _: self.changed.emit())
        return w

    def _build_output_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.fmt_seg = Segmented(FORMAT_OPTS, "mp4")
        self.res_seg = Segmented(RES_OPTS, "src")
        self.fps_seg = Segmented(FPS_OPTS, "src")
        self.codec_seg = Segmented(CODEC_OPTS, "h264")
        self.res_note = label("", "Faint")
        self.res_note.setStyleSheet("font-size:11px;")
        self.fps_note = label("", "Faint")
        self.fps_note.setStyleSheet("font-size:11px;")
        self.g_fmt = _group("Format", self.fmt_seg)
        self.g_res = _group("Resolution", self.res_seg, self.res_note)
        self.g_fps = _group("Frame rate", self.fps_seg, self.fps_note)
        self.g_codec = _group("Video codec", self.codec_seg)
        for g in (self.g_fmt, self.g_res, self.g_fps, self.g_codec):
            v.addWidget(g)

        qw = QWidget()
        qv = QVBoxLayout(qw)
        qv.setContentsMargins(0, 0, 0, 0)
        qv.setSpacing(4)
        self.quality = QSlider(Qt.Horizontal)
        self.quality.setRange(2, 20)  # x5 -> 10..100
        self.quality.setPageStep(1)
        self.quality.setAccessibleName("Quality")
        self.quality.setCursor(Qt.PointingHandCursor)
        qv.addWidget(self.quality)
        ends = QHBoxLayout()
        ends.addWidget(label("Smaller file", "Faint"))
        ends.addStretch(1)
        ends.addWidget(label("Best quality", "Faint"))
        for i in range(ends.count()):
            it = ends.itemAt(i).widget()
            if it:
                it.setStyleSheet("font-size:11px;")
        qv.addLayout(ends)
        self.quality_lbl = label("High")
        self.quality_lbl.setStyleSheet(f"color:{theme.ACCENT};font-size:12px;font-weight:600;")
        self.g_quality = _group("Quality", qw, self.quality_lbl)
        v.addWidget(self.g_quality)

        aw = QWidget()
        ah = QHBoxLayout(aw)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(8)
        self.audio_toggle = Toggle(True)
        self.audio_toggle.setAccessibleName("Keep audio")
        self.audio_toggle.setToolTip("Keep audio")
        self.abr_seg = Segmented(ABR_OPTS, 192)
        ah.addWidget(self.audio_toggle)
        ah.addWidget(self.abr_seg, 1)
        self.g_audio = _group("Audio", aw)
        v.addWidget(self.g_audio)

        # videos with dubbed / AI-translated audio: choose the track (defaults to the original language)
        self.track_box = QComboBox()
        self.track_box.setAccessibleName("Audio track")
        self.track_box.setCursor(Qt.PointingHandCursor)
        self.track_box.currentIndexChanged.connect(self._on_track)
        self.track_note = label("", "Faint")
        self.track_note.setStyleSheet("font-size:11px;")
        self.g_track = _group("Audio language", self.track_box, self.track_note)
        self.g_track.hide()
        v.addWidget(self.g_track)

        self.fmt_seg.changed.connect(self._on_format)
        self.res_seg.changed.connect(lambda val: self._set(resolution=val))
        self.fps_seg.changed.connect(lambda val: self._set(fps=val))
        self.codec_seg.changed.connect(lambda val: self._set(codec=val))
        self.quality.valueChanged.connect(lambda val: self._set(quality=val * 5))
        self.audio_toggle.toggled.connect(lambda on: self._set(audio=on))
        self.abr_seg.changed.connect(lambda val: self._set(audio_bitrate=val))
        return w

    def _focus_frame(self, edit: QLineEdit, box: QFrame):
        self._focus_watch = FocusWatcher(box, self)
        edit.installEventFilter(self._focus_watch)

    # ------------------------------------------------------------ API
    def set_tab(self, tab: str):
        self.tabs.set_value(tab)
        self._on_tab(tab)

    def _on_tab(self, tab):
        self.pages.setCurrentIndex(0 if tab == "file" else 1)

    def load_settings(self, out: OutputSettings, precise: bool, folder: str):
        self._loading = True
        self._out = encode.normalize(out)
        self._precise = precise
        self.cut_seg.set_value(precise)
        self.folder_edit.setText(folder)
        self.folder_edit.setCursorPosition(0)
        self.folder_edit.setToolTip(folder)
        self._sync_controls()
        self._loading = False
        self._refresh()

    def output(self) -> OutputSettings:
        return encode.normalize(self._out)

    def precise(self) -> bool:
        return self._precise

    def folder(self) -> str:
        return self.folder_edit.text().strip()

    def set_folder(self, f: str):
        self.folder_edit.setText(f)
        self.folder_edit.setCursorPosition(0)
        self.changed.emit()

    def file_name(self) -> str:
        return self.name_edit.text()

    def set_file_name(self, n: str):
        self.name_edit.setText(n)
        self.name_edit.setCursorPosition(0)

    def set_source(self, height: int | None, fps: float | None, heights: list[int] | None = None):
        self.src_height, self.src_fps = height, fps
        for val, _ in RES_OPTS:
            if val != "src":
                ok = height is None or val <= height
                self.res_seg.set_option_enabled(val, ok)
        if self._out.resolution != "src" and height and self._out.resolution > height:
            self._out.resolution = "src"
        self._sync_controls()
        self._refresh()

    def set_audio_tracks(self, tracks: list, current: str | None):
        """tracks: [(lang, label, is_original)]. Hidden when the video has a single audio track."""
        self._loading_tracks = True
        self.track_box.clear()
        for lang, name, orig in tracks:
            self.track_box.addItem(f"{name}  ·  original" if orig else name, lang)
        i = self.track_box.findData(current)
        self.track_box.setCurrentIndex(max(0, i))
        self._loading_tracks = False
        self.g_track.setVisible(len(tracks) > 1)
        self.track_note.setText(f"{len(tracks)} tracks" if len(tracks) > 1 else "")

    def audio_lang(self) -> str | None:
        return self.track_box.currentData() if self.g_track.isVisible() or self.track_box.count() > 1 else None

    def _on_track(self, _i):
        if not getattr(self, "_loading_tracks", False):
            self.audioTrackChanged.emit(self.track_box.currentData())

    def set_clip_len(self, length: float):
        self.clip_len = length
        self._refresh()

    def set_can_download(self, on: bool):
        self.download_btn.setEnabled(on)

    # ------------------------------------------------------------ internals
    def _set(self, **kw):
        if self._loading:
            return
        self._out = encode.normalize(replace(self._out, **kw))
        self._sync_controls()
        self._refresh()
        self.changed.emit()

    def _on_format(self, fmt):
        if self._loading:
            return
        kw = {"format": fmt}
        if fmt == "gif":
            if self._out.fps == "src":
                kw["fps"] = 15
            if self._out.resolution == "src" and (self.src_height is None or self.src_height > 480):
                kw["resolution"] = 480
        self._set(**kw)

    def _on_cut(self, precise):
        self._precise = bool(precise)
        self._refresh()
        if not self._loading:
            self.changed.emit()

    def _sync_controls(self):
        o = self._out
        was = self._loading
        self._loading = True
        self.fmt_seg.set_value(o.format)
        self.res_seg.set_value(o.resolution)
        self.fps_seg.set_value(o.fps)
        self.codec_seg.set_value(o.codec)
        self.quality.setValue(o.quality // 5)
        self.audio_toggle.setChecked(o.audio)
        self.abr_seg.set_value(o.audio_bitrate)
        vid = encode.has_video(o)
        for g in (self.g_res, self.g_fps, self.g_quality):
            g.setEnabled(vid)
        self.g_codec.setEnabled(vid and o.format != "gif")
        for c, _ in CODEC_OPTS:
            self.codec_seg.set_option_enabled(c, encode.codec_allowed(o.format, c))
        self.g_audio.setEnabled(o.format != "gif")
        self.audio_toggle.setEnabled(o.format not in ("gif", "mp3"))
        self.abr_seg.setEnabled(encode.has_audio(o))
        q = o.quality
        self.quality_lbl.setText("Best" if q >= 85 else "High" if q >= 60 else "Medium" if q >= 35 else "Low")
        self._loading = was

    def _refresh(self):
        o = self.output()
        self.ext_lbl.setText("." + encode.EXT[o.format])
        self.cut_help.setText("Re-encodes so the clip starts on the exact frame. Slower." if self._precise else
                              "Cuts on the nearest keyframe. Near-instant, may start up to a few seconds early.")
        src_fps = round(self.src_fps) if self.src_fps else None
        self.res_note.setText(f"Source {self.src_height}p" if self.src_height else "")
        if o.fps == "src":
            self.fps_note.setText(f"Source {src_fps} fps" if src_fps else "")
        elif src_fps and o.fps > src_fps:
            self.fps_note.setText("Above source: frames are repeated")
        elif src_fps and o.fps < src_fps:
            self.fps_note.setText(f"Drops frames from {src_fps}")
        else:
            self.fps_note.setText("")

        copy = not encode.needs_reencode(o, self._precise, None, self.src_height, self.src_fps)
        est = encode.estimate_size_mb(o, self.clip_len or 1, self.src_height, self.src_fps)
        est_txt = "—" if self.clip_len <= 0 else (f"{est:.0f}" if est >= 100 else f"{est:.1f}")
        self.est_lbl.setText(f"<span style='color:{theme.TEXT_2};font-size:12px'>Estimated size</span>"
                             f"&nbsp;&nbsp;<span style='font-family:\"{theme.FONT_MONO}\";font-size:13px;"
                             f"font-weight:600'>{'≈ ' + est_txt + ' MB' if est_txt != '—' else '—'}</span>")
        self.encode_tag.setText("Stream copy" if copy else "Re-encode")
        self.encode_tag.setProperty("good", copy)
        repolish(self.encode_tag)
        self.encode_tag.setToolTip("Fast: copies the original streams, no quality loss (if YouTube serves H.264)."
                                   if copy else "Your settings need a re-encode. Slower, but exact.")
        parts = encode.summary_parts(o, self.src_height, self.src_fps)
        from ..core.timefmt import fmt_time
        self.summary_lbl.setText(" · ".join([fmt_time(self.clip_len, tenths=True)] + parts[:4]))
        for i, c in enumerate(self.chip_labels):
            if i < len(parts):
                c.setText(parts[i])
                c.adjustSize()
                c.show()
            else:
                c.hide()
        self.chips.invalidate()
        self.chips_w.updateGeometry()
        dot = " •" if not o.is_default() else ""
        self.tabs.set_label("output", "Output" + dot)
