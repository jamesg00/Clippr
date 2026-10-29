"""The five tool windows: To MP3, Convert, Images, Resize, Compress."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QSlider, QSpinBox, QVBoxLayout, QWidget

from ...core import audio_dl, compress, convert, images, paths
from .. import theme
from ..widgets import Segmented, label
from .base import ChoiceGrid, ToolWindow, mb, option_group, toggle_row


def _quality_slider(value: int, lo: int = 10, hi: int = 100) -> tuple[QWidget, QSlider, object]:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    s.setAccessibleName("Quality")
    v.addWidget(s)
    ends = QHBoxLayout()
    a, b = label("Smaller file", "Faint"), label("Best quality", "Faint")
    for x in (a, b):
        x.setStyleSheet("font-size:11px;")
    ends.addWidget(a)
    ends.addStretch(1)
    ends.addWidget(b)
    v.addLayout(ends)
    note = label("")
    note.setStyleSheet(f"color:{theme.ACCENT};font-size:12px;font-weight:600;")

    def upd(val):
        note.setText(f"{val}%")

    s.valueChanged.connect(upd)
    upd(value)
    return w, s, note


# ================================================================== To MP3
class AudioTool(ToolWindow):
    KEY = "audio"
    TITLE = "To MP3"
    ICON = "music"
    URL_INPUT = True
    URL_SITES = "YouTube, Instagram, X or SoundCloud"
    AUDIO_LINKS = True
    ROW_ICON = "music"
    DROP_TITLE = "Paste links to save their audio"
    DROP_HINT = "YouTube, Instagram, X and SoundCloud. Paste several at once and they'll download one after another."
    START_LABEL = "Download audio"
    NEXT_TO_ORIGINALS = None

    def build_options(self, lay):
        o = self.opts
        self.fmt = Segmented([(f, f.upper()) for f in audio_dl.AUDIO_FORMATS], o.get("format", "mp3"), tall=True)
        lay.addWidget(option_group("Format", self.fmt))
        self.br = Segmented([(b, f"{b}k") for b in audio_dl.BITRATES], o.get("bitrate", 320))
        self.br_group = option_group("Quality", self.br)
        lay.addWidget(self.br_group)
        self.fmt_note = label("", "Faint", wrap=True)
        self.fmt_note.setStyleSheet("font-size:12px;")
        lay.addWidget(self.fmt_note)
        w1, self.cover = toggle_row("Add cover art", o.get("cover", True), "Embeds the thumbnail or track artwork as album art")
        w2, self.tags = toggle_row("Add title & artist tags", o.get("tags", True))
        lay.addWidget(w1)
        lay.addWidget(w2)
        self.fmt.changed.connect(lambda _: (self._sync(), self.remember()))
        self.br.changed.connect(lambda _: self.remember())
        self.cover.toggled.connect(lambda _: self.remember())
        self.tags.toggled.connect(lambda _: self.remember())
        self._sync()

    def _sync(self):
        f = self.fmt.value()
        lossless = f in audio_dl.LOSSLESS
        self.br_group.setEnabled(not lossless)
        self.cover.setEnabled(f in audio_dl.THUMB_OK)
        self.fmt_note.setText({"mp3": "Plays everywhere.", "m4a": "AAC: smaller than MP3 at the same quality.",
                               "wav": "Uncompressed, big files. Quality setting doesn't apply.",
                               "flac": "Lossless and compressed. Quality setting doesn't apply.",
                               "opus": "Most efficient; not every player supports it."}[f])

    def options(self):
        return {"format": self.fmt.value(), "bitrate": self.br.value(), "cover": self.cover.isChecked(),
                "tags": self.tags.isChecked()}

    def task(self, item, o):
        ctx = self.ctx

        def fn(progress, log, cancel):
            return audio_dl.download_audio(item["src"], o["format"], o["bitrate"], o["folder"], ctx.ffmpeg, cancel,
                                           progress, log, cookies=ctx.cfg.cookies, cover=o["cover"],
                                           metadata=o["tags"])
        return fn

    def describe(self, item, result):
        p = Path(result)
        try:
            size = mb(p.stat().st_size)
        except OSError:
            size = ""
        return f"Saved {p.name} · {size}", result

    def paste_shortcut(self):
        """Ctrl+V anywhere on this page (outside the link field) adds the clipboard's links."""
        if not self.url_edit.hasFocus():
            self._paste()


# ================================================================== Convert (video, audio and pictures)
IMG_NOTES = {"png": "Lossless, keeps transparency.", "jpg": "Small photos; transparency becomes white.",
             "webp": "Smaller than JPG, keeps transparency.", "bmp": "Uncompressed.",
             "heic": "iPhone's format: about half the size of JPG. Some Windows apps need the HEIF extension.",
             "tiff": "Lossless, for print and editing.", "gif": "256 colours.",
             "ico": "Windows icon with sizes up to 256 px."}


def media_kind(src: str) -> str:
    """'image' or 'media'. An animated GIF counts as video, a still GIF as a picture."""
    ext = Path(src).suffix.lower()
    if ext == ".gif":
        try:
            from PIL import Image
            with Image.open(src) as im:
                return "media" if getattr(im, "n_frames", 1) > 1 else "image"
        except Exception:  # noqa: BLE001
            return "image"
    return "image" if ext in images.IMAGE_IN else "media"


class ConvertTool(ToolWindow):
    """One converter for everything: video and audio go through ffmpeg, pictures through Pillow.
    Each kind has its own target format, so a mixed list converts in one go."""

    KEY = "convert"
    TITLE = "Convert"
    ICON = "repeat"
    ACCEPTS = convert.MEDIA_IN | images.IMAGE_IN
    ROW_ICON = "film"
    DROP_TITLE = "Drop videos, audio or pictures"
    DROP_HINT = "MP4, MOV, MP3, WAV, FLAC… and PNG, JPG, WebP, HEIC. Mix them freely; folders and pasted pictures work too."
    START_LABEL = "Convert"

    def __init__(self, ctx):
        # settings from the old separate Images window carry over
        old = ctx.cfg.tools.get("images") or {}
        cur = ctx.cfg.tools.setdefault(self.KEY, {})
        for k_old, k_new in (("format", "img_format"), ("quality", "img_quality"), ("meta", "meta")):
            if k_old in old and k_new not in cur:
                cur[k_new] = old[k_old]
        super().__init__(ctx)

    def row_icon(self, src: str) -> str:
        if media_kind(src) == "image":
            return "image"
        return "music" if Path(src).suffix.lower() in {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac",
                                                       ".wma", ".aiff", ".aif", ".alac"} else "film"

    def build_options(self, lay):
        o = self.opts
        # ---- video & audio
        self.media_head = self._section("Video & audio", "film")
        lay.addWidget(self.media_head)
        self.fmt = ChoiceGrid([("Video", [("mp4", "MP4"), ("mkv", "MKV"), ("webm", "WebM"), ("mov", "MOV"),
                                          ("avi", "AVI"), ("gif", "GIF")]),
                               ("Audio", [("mp3", "MP3"), ("m4a", "M4A"), ("wav", "WAV"), ("flac", "FLAC"),
                                          ("ogg", "OGG"), ("opus", "Opus")])],
                              o.get("format", "mp4"))
        lay.addWidget(option_group("Convert to", self.fmt))
        self.res = Segmented([("src", "Source"), (1080, "1080p"), (720, "720p"), (480, "480p")], o.get("resolution", "src"))
        self.res_group = option_group("Resolution", self.res)
        lay.addWidget(self.res_group)
        qw, self.quality, qnote = _quality_slider(o.get("quality", 70))
        self.q_group = option_group("Quality", qw, qnote)
        lay.addWidget(self.q_group)
        self.abr = Segmented([(128, "128k"), (192, "192k"), (256, "256k"), (320, "320k")], o.get("abr", 192))
        self.abr_group = option_group("Audio bitrate", self.abr)
        lay.addWidget(self.abr_group)

        # ---- pictures
        lay.addSpacing(6)
        self.img_head = self._section("Pictures", "image")
        lay.addWidget(self.img_head)
        row1 = [("png", "PNG"), ("jpg", "JPG"), ("webp", "WebP")] + ([("heic", "HEIC")] if images.HEIF else [])
        self.img_fmt = ChoiceGrid([(None, row1), (None, [("bmp", "BMP"), ("tiff", "TIFF"), ("gif", "GIF"),
                                                         ("ico", "ICO")])], o.get("img_format", "png"))
        lay.addWidget(option_group("Convert to", self.img_fmt))
        iqw, self.img_quality, iqnote = _quality_slider(o.get("img_quality", 90), 30, 100)
        self.img_q_group = option_group("Quality", iqw, iqnote)
        lay.addWidget(self.img_q_group)
        self.img_note = label("", "Faint", wrap=True)
        self.img_note.setStyleSheet("font-size:12px;")
        lay.addWidget(self.img_note)
        w, self.meta = toggle_row("Keep photo info (EXIF)", o.get("meta", False),
                                  "Camera, date and location data. Off removes it.")
        lay.addWidget(w)

        for sig in (self.fmt.changed, self.res.changed, self.abr.changed, self.img_fmt.changed):
            sig.connect(lambda _: (self._sync(), self.remember()))
        self.quality.valueChanged.connect(lambda _: self.remember())
        self.img_quality.valueChanged.connect(lambda _: self.remember())
        self.meta.toggled.connect(lambda _: self.remember())
        self._sync()

    def _section(self, title: str, icon_name: str):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        ic = label("")
        ic.setPixmap(theme.icon_pixmap(icon_name, theme.ACCENT, 15))
        t = label(title)
        t.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:14px;font-weight:600;")
        cnt = label("", "Faint")
        cnt.setStyleSheet("font-size:12px;")
        h.addWidget(ic)
        h.addWidget(t)
        h.addStretch(1)
        h.addWidget(cnt)
        w.count = cnt
        return w

    def _sync(self):
        f = self.fmt.value()
        is_video = f in convert.VIDEO_OUT
        self.res_group.setEnabled(is_video)
        self.q_group.setEnabled(is_video)
        self.abr_group.setEnabled(f not in ("wav", "flac", "gif"))
        fi = self.img_fmt.value()
        self.img_q_group.setEnabled(fi in ("jpg", "webp", "heic"))
        self.img_note.setText(IMG_NOTES.get(fi, ""))
        self.update_summary()

    def update_summary(self):
        if not hasattr(self, "img_head"):
            return
        kinds = [it.get("kind") or media_kind(it["src"]) for it in self.items.values() if it["status"] == "pending"]
        nm, ni = kinds.count("media"), kinds.count("image")
        self.media_head.count.setText(f"{nm} in the list" if nm else "none in the list")
        self.img_head.count.setText(f"{ni} in the list" if ni else "none in the list")

    def _add_item(self, src, name, sub):
        iid = super()._add_item(src, name, sub)
        self.items[iid]["kind"] = media_kind(src) if Path(src).exists() else "media"
        self.update_summary()
        return iid

    def options(self):
        return {"format": self.fmt.value(), "resolution": self.res.value(), "quality": self.quality.value(),
                "abr": self.abr.value(), "img_format": self.img_fmt.value(), "img_quality": self.img_quality.value(),
                "meta": self.meta.isChecked()}

    def needs_ffmpeg(self):
        return any(it.get("kind") == "media" for it in self.items.values() if it["status"] == "pending")

    def item_label(self, src):
        name, size = super().item_label(src)
        if media_kind(src) == "image":
            try:
                from PIL import Image
                with Image.open(src) as im:
                    return name, f"{im.size[0]}×{im.size[1]} · {size}"
            except Exception:  # noqa: BLE001
                pass
        return name, size

    def task(self, item, o):
        ctx = self.ctx
        if item.get("kind") == "image":
            def fn(progress, log, cancel):
                progress(None, "Converting…")
                return images.convert_image(item["src"], o["img_format"], o["folder"], o["img_quality"], o["meta"])
            return fn

        def fn(progress, log, cancel):
            return convert.convert_file(item["src"], o["format"], o["folder"], ctx.ffmpeg, paths.ffprobe_path(),
                                        cancel, progress, log, o["quality"], o["resolution"], o["abr"])
        return fn

    def describe(self, item, result):
        p = Path(result)
        return f"→ {p.name} · {mb(p.stat().st_size)}", result


# ================================================================== picture base (used by Resize)
class ImagesTool(ToolWindow):
    KEY = "images"
    TITLE = "Images"
    ICON = "image"
    ACCEPTS = images.IMAGE_IN
    ROW_ICON = "image"
    DROP_TITLE = "Drop pictures to convert"
    DROP_HINT = "PNG, JPG, WebP, HEIC, BMP, TIFF, GIF, ICO. Folders work, and so does pasting a picture copied from the web."
    START_LABEL = "Convert pictures"

    def build_options(self, lay):
        o = self.opts
        row1 = [("png", "PNG"), ("jpg", "JPG"), ("webp", "WebP")] + ([("heic", "HEIC")] if images.HEIF else [])
        self.fmt = ChoiceGrid([(None, row1), (None, [("bmp", "BMP"), ("tiff", "TIFF"), ("gif", "GIF"), ("ico", "ICO")])],
                              o.get("format", "png"))
        lay.addWidget(option_group("Convert to", self.fmt))
        qw, self.quality, qnote = _quality_slider(o.get("quality", 90), 30, 100)
        self.q_group = option_group("Quality", qw, qnote)
        lay.addWidget(self.q_group)
        self.note = label("", "Faint", wrap=True)
        self.note.setStyleSheet("font-size:12px;")
        lay.addWidget(self.note)
        w, self.meta = toggle_row("Keep photo info (EXIF)", o.get("meta", False),
                                  "Camera, date and location data. Off removes it.")
        lay.addWidget(w)
        self.fmt.changed.connect(lambda _: (self._sync(), self.remember()))
        self.quality.valueChanged.connect(lambda _: self.remember())
        self.meta.toggled.connect(lambda _: self.remember())
        self._sync()

    def _sync(self):
        f = self.fmt.value()
        self.q_group.setEnabled(f in ("jpg", "webp", "heic"))
        self.note.setText({"png": "Lossless, keeps transparency.", "jpg": "Small photos; transparency becomes white.",
                           "webp": "Smaller than JPG, keeps transparency.", "bmp": "Uncompressed.",
                           "heic": "iPhone's format: about half the size of JPG. Some Windows apps need the HEIF extension.",
                           "tiff": "Lossless, for print and editing.", "gif": "256 colours.",
                           "ico": "Windows icon with sizes up to 256 px."}.get(f, ""))

    def options(self):
        return {"format": self.fmt.value(), "quality": self.quality.value(), "meta": self.meta.isChecked()}

    def needs_ffmpeg(self):
        return False

    def task(self, item, o):
        def fn(progress, log, cancel):
            progress(None, "Converting…")
            return images.convert_image(item["src"], o["format"], o["folder"], o["quality"], o["meta"])
        return fn

    def describe(self, item, result):
        p = Path(result)
        return f"→ {p.name} · {mb(p.stat().st_size)}", result

    def item_label(self, src):
        name, size = super().item_label(src)
        try:
            from PIL import Image
            with Image.open(src) as im:
                return name, f"{im.size[0]}×{im.size[1]} · {size}"
        except Exception:  # noqa: BLE001
            return name, size


# ================================================================== Resize
class ResizeTool(ImagesTool):
    """Batch resize + a Photoshop-style free-transform editor for the selected picture."""

    KEY = "resize"
    TITLE = "Resize"
    ICON = "resize"
    DROP_TITLE = "Drop pictures to resize"
    DROP_HINT = "Drop, paste or copy a picture from the web. PNG, JPG, WebP, HEIC, BMP, TIFF, GIF, ICO."
    START_LABEL = "Resize pictures"

    # ------------------------------------------------------------ editor + list
    def build_list_area(self, scroll):
        from PySide6.QtWidgets import QSplitter

        from .image_editor import ImageEditor
        self.sel: int | None = None
        self._previews: dict[str, tuple] = {}
        self.editor = ImageEditor()
        self.editor.edited.connect(self._on_edited)
        self.editor.resetRequested.connect(self._on_reset)
        self.editor.applyAllRequested.connect(self._apply_all)
        sp = QSplitter(Qt.Vertical)
        sp.setChildrenCollapsible(False)
        sp.setHandleWidth(8)
        sp.addWidget(self.editor)
        scroll.setMinimumHeight(110)
        sp.addWidget(scroll)
        sp.setStretchFactor(0, 4)
        sp.setStretchFactor(1, 1)
        sp.setSizes([560, 150])
        self.splitter = sp
        return sp

    def _preview(self, src: str):
        if src not in self._previews:
            from .image_editor import load_preview
            try:
                self._previews[src] = load_preview(src)
            except Exception:  # noqa: BLE001
                self._previews[src] = (None, 1, 1)
        return self._previews[src]

    def batch_transform(self, iw: int, ih: int):
        m, w, h = self._sizes()
        return images.initial_transform(iw, ih, m, self.pct.value(), w, h, self.aspect.isChecked())

    def select_item(self, iid: int):
        it = self.items.get(iid)
        if not it:
            return
        self.sel = iid
        for other in self.items.values():
            other["row"].set_selected(other["id"] == iid)
        img, iw, ih = self._preview(it["src"])
        if img is None:
            self.editor.show_image(None, None, 1, 1, None, False)
            self.status.set_status("Couldn't open that picture for editing.", theme.DANGER)
            return
        t = it.get("edit") or self.batch_transform(iw, ih)
        self.editor.show_image(it["src"], img, iw, ih, t, it.get("edit") is not None)
        self.update_summary()

    def _add_item(self, src, name, sub):
        iid = super()._add_item(src, name, sub)
        self.items[iid]["edit"] = None
        if self.sel is None or self.sel not in self.items:
            self.select_item(iid)
        return iid

    def remove_item(self, iid):
        super().remove_item(iid)
        if iid == self.sel:
            self.sel = None
            nxt = next((i for i in self.order if i in self.items), None)
            if nxt is not None:
                self.select_item(nxt)
            else:
                self.editor.show_image(None, None, 1, 1, None, False)

    def _edited_text(self, t) -> str:
        return f"Custom · {t.canvas_w}×{t.canvas_h} px" + (f" · {t.rot:.0f}°" if abs(t.rot) > 0.05 else "")

    def _on_edited(self, t):
        it = self.items.get(self.sel)
        if not it or it["status"] == "running":
            return
        it["edit"] = t
        if it["status"] != "done":
            it["row"].set_pending(self._edited_text(t))
        self._refresh()

    def _on_reset(self):
        it = self.items.get(self.sel)
        if not it:
            return
        it["edit"] = None
        if it["status"] == "pending":
            it["row"].set_pending(it["sub"])
        img, iw, ih = self._preview(it["src"])
        self.editor.set_transform(self.batch_transform(iw, ih), False)
        self._refresh()

    def _apply_all(self):
        """Copy the selected picture's canvas + placement to every other waiting picture."""
        cur = self.items.get(self.sel)
        if not cur or self.editor.t is None:
            return
        t = self.editor.t
        _, iw, ih = self._preview(cur["src"])
        n = 0
        for it in self.items.values():
            if it is cur or it["status"] != "pending":
                continue
            try:
                from PIL import Image, ImageOps
                with Image.open(it["src"]) as im:
                    w2, h2 = ImageOps.exif_transpose(im).size
            except Exception:  # noqa: BLE001
                continue
            # same canvas, same on-canvas width (height follows the picture's own proportions)
            s = t.sx * iw / w2
            t2 = t.copy()
            t2.sx = s
            t2.sy = s * (t.sy / t.sx if t.sx else 1)
            it["edit"] = t2
            it["row"].set_pending(self._edited_text(t2))
            n += 1
        cur["edit"] = t.copy()
        self.status.set_status(f"Applied to {n} more picture{'s' if n != 1 else ''}.", theme.ACCENT)
        self._refresh()

    # ------------------------------------------------------------ options
    def build_options(self, lay):
        o = self.opts
        self.mode = Segmented([("percent", "Percent"), ("fit", "Fit"), ("exact", "Exact"), ("crop", "Crop")],
                              o.get("mode", "fit"), tall=True)
        lay.addWidget(option_group("Batch: how", self.mode))
        self.mode_note = label("", "Faint", wrap=True)
        self.mode_note.setStyleSheet("font-size:12px;")
        lay.addWidget(self.mode_note)

        self.pct_row = QWidget()
        pr = QHBoxLayout(self.pct_row)
        pr.setContentsMargins(0, 0, 0, 0)
        self.pct = QSlider(Qt.Horizontal)
        self.pct.setRange(5, 400)
        self.pct.setValue(o.get("percent", 50))
        self.pct.setAccessibleName("Scale percent")
        self.pct_lbl = label("")
        self.pct_lbl.setFixedWidth(52)
        self.pct_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.pct_lbl.setStyleSheet(f"font-family:'{theme.FONT_MONO}';color:{theme.ACCENT};font-weight:600;")
        pr.addWidget(self.pct, 1)
        pr.addWidget(self.pct_lbl)
        self.pct_group = option_group("Scale", self.pct_row)
        lay.addWidget(self.pct_group)

        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QPushButton
        self.size_row = QWidget()
        sr = QHBoxLayout(self.size_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(6)
        self.w = QSpinBox()
        self.h = QSpinBox()
        for sb, val, name in ((self.w, o.get("width", 1920), "Width"), (self.h, o.get("height", 1080), "Height")):
            sb.setRange(0, 20000)
            sb.setSpecialValueText("auto")
            sb.setValue(val)
            sb.setSuffix(" px")
            sb.setAccessibleName(name)
            sb.setButtonSymbols(QSpinBox.NoButtons)
            sb.setKeyboardTracking(False)
        # the chain: lock aspect ratio (Photoshop's link icon)
        self.aspect = QPushButton()
        self.aspect.setObjectName("Chain")
        self.aspect.setCheckable(True)
        self.aspect.setChecked(o.get("keep_aspect", True))
        self.aspect.setFixedSize(30, 30)
        self.aspect.setIconSize(QSize(16, 16))
        self.aspect.setCursor(Qt.PointingHandCursor)
        self.aspect.setAccessibleName("Lock aspect ratio")
        sr.addWidget(self.w, 1)
        sr.addWidget(self.aspect)
        sr.addWidget(self.h, 1)
        self.size_group = option_group("Size", self.size_row)
        lay.addWidget(self.size_group)
        self.aspect_w = self.aspect  # kept for older callers

        self.fmt = Segmented([("same", "Same"), ("png", "PNG"), ("jpg", "JPG"), ("webp", "WebP")] +
                             ([("heic", "HEIC")] if images.HEIF else []), o.get("format", "same"))
        lay.addWidget(option_group("Save as", self.fmt))
        sfx = QLineEdit(o.get("suffix", "_resized"))
        sfx.setAccessibleName("File name suffix")
        sfx.setPlaceholderText("_resized")
        self.suffix = sfx
        lay.addWidget(option_group("Add to file names", sfx))
        self.preview = label("", "Faint", wrap=True)
        self.preview.setStyleSheet(f"font-size:12px;font-family:'{theme.FONT_MONO}';")
        lay.addWidget(self.preview)
        tip = label("Pictures you change in the editor (marked Custom) use their own canvas instead of the batch "
                    "settings. Reset in the editor puts them back.", "Faint", wrap=True)
        tip.setStyleSheet("font-size:11px;")
        lay.addWidget(tip)

        self._linking = False
        self.mode.changed.connect(lambda _: (self._sync(), self.remember()))
        self.pct.valueChanged.connect(lambda _: (self._sync(), self.remember()))
        self.w.valueChanged.connect(lambda val: self._linked("w", val))
        self.h.valueChanged.connect(lambda val: self._linked("h", val))
        self.aspect.toggled.connect(lambda _: (self._sync(), self.remember()))
        self.fmt.changed.connect(lambda _: self.remember())
        sfx.textEdited.connect(lambda _: self.remember())
        self._ratio = (o.get("width", 1920) or 16) / max(1, o.get("height", 1080) or 9)
        self._sync()

    def _linked(self, which: str, val: int):
        """With the chain locked, editing one side updates the other (selected picture's proportions in Exact)."""
        if self._linking:
            return
        if self.aspect.isChecked() and val:
            ratio = self._ratio
            if self.mode.value() == "exact" and self.sel in self.items:
                _, iw, ih = self._preview(self.items[self.sel]["src"])
                ratio = iw / max(1, ih)
            self._linking = True
            if which == "w":
                self.h.setValue(max(1, round(val / ratio)))
            else:
                self.w.setValue(max(1, round(val * ratio)))
            self._linking = False
        if self.w.value() and self.h.value():
            self._ratio = self.w.value() / self.h.value()
        self._sync()
        self.remember()

    def _sync(self):
        m = self.mode.value()
        self.pct_group.setVisible(m == "percent")
        self.size_group.setVisible(m != "percent")
        on = self.aspect.isChecked()
        self.aspect.setIcon(theme.icon("link" if on else "unlink", theme.ACCENT if on else theme.TEXT_3, 16))
        self.aspect.setToolTip("Aspect ratio locked: changing one side changes the other" if on else
                               "Aspect ratio unlocked")
        self.pct_lbl.setText(f"{self.pct.value()}%")
        self.mode_note.setText({"percent": "Scale every picture by the same amount.",
                                "fit": "Shrink to fit inside the box. Proportions are kept.",
                                "exact": "Set an exact width and height." + (" Proportions are kept." if on else ""),
                                "crop": "Fill the exact size, cropping the edges (good for thumbnails)."}[m])
        # keep the editor in step for a picture that hasn't been customised
        if getattr(self, "sel", None) in getattr(self, "items", {}):
            it = self.items[self.sel]
            if it.get("edit") is None and self.editor.t is not None:
                _, iw, ih = self._preview(it["src"])
                self.editor.set_transform(self.batch_transform(iw, ih), False)
        self.update_summary()

    def ready(self):
        pending = [it for it in self.items.values() if it["status"] == "pending"]
        if pending and all(it.get("edit") is not None for it in pending):
            return True
        m = self.mode.value() if hasattr(self, "mode") else "percent"
        if m == "percent":
            return True
        return bool(self.w.value() or self.h.value()) and (m == "exact" or (self.w.value() and self.h.value())
                                                           or m == "fit")

    def _sizes(self):
        m = self.mode.value()
        w = self.w.value() or None
        h = self.h.value() or None
        if m == "fit":
            w = w or 100000
            h = h or 100000
        if m == "crop":
            w = w or h
            h = h or w
        if m == "exact" and not self.aspect.isChecked():
            pass
        return m, w, h

    def update_summary(self):
        if not hasattr(self, "preview"):
            return
        it = self.items.get(getattr(self, "sel", None)) or next(
            (i for i in self.items.values() if i["status"] == "pending"), None)
        if not it:
            self.preview.setText("")
            return
        try:
            _, sw, sh = self._preview(it["src"])
            if it.get("edit") is not None:
                t = it["edit"]
                self.preview.setText(f"{sw}×{sh} → {t.canvas_w}×{t.canvas_h} (custom)")
                return
            m, w, h = self._sizes()
            tw, th = images.target_size(sw, sh, m, self.pct.value(), w, h, self.aspect.isChecked())
            self.preview.setText(f"{sw}×{sh} → {tw}×{th}")
        except Exception:  # noqa: BLE001
            self.preview.setText("")

    def options(self):
        return {"mode": self.mode.value(), "percent": self.pct.value(), "width": self.w.value(),
                "height": self.h.value(), "keep_aspect": self.aspect.isChecked(), "format": self.fmt.value(),
                "suffix": self.suffix.text() or "_resized"}

    def task(self, item, o):
        m, w, h = self._sizes()
        edit = item.get("edit")
        edit = edit.copy() if edit is not None else None

        def fn(progress, log, cancel):
            if edit is not None:
                progress(None, "Rendering…")
                return images.edit_image(item["src"], edit, o["format"], 92, o["folder"], o["suffix"])
            progress(None, "Resizing…")
            return images.resize_image(item["src"], m, o["percent"], w, h, o["keep_aspect"], o["format"], 92,
                                       o["folder"], o["suffix"])
        return fn

    def describe(self, item, result):
        path, old, new = result
        return f"{old[0]}×{old[1]} → {new[0]}×{new[1]} · {Path(path).name}", path


# ================================================================== Compress
LEVEL_TEXT = {
    "light": "Barely visible changes. PDF images at 200 dpi, photos at quality 85, video CRF 26.",
    "balanced": "Good for sharing. PDF images at 150 dpi, photos ≤ 2560 px, video up to 1080p.",
    "strong": "Smallest files. PDF images at 100 dpi, photos ≤ 1600 px, video up to 720p.",
}


class CompressTool(ToolWindow):
    KEY = "compress"
    TITLE = "Compress"
    ICON = "compress"
    ACCEPTS = None
    ROW_ICON = "file"
    DROP_TITLE = "Drop files to make them smaller"
    DROP_HINT = "PDFs, pictures, videos and audio get re-compressed. Anything else is packed into a ZIP."
    START_LABEL = "Compress"

    def build_options(self, lay):
        self.level = Segmented([("light", "Light"), ("balanced", "Balanced"), ("strong", "Strong")],
                               self.opts.get("level", "balanced"), tall=True)
        lay.addWidget(option_group("Strength", self.level))
        self.level_note = label("", "Faint", wrap=True)
        self.level_note.setStyleSheet("font-size:12px;")
        lay.addWidget(self.level_note)
        kinds = label("", "Faint", wrap=True)
        kinds.setTextFormat(Qt.RichText)
        kinds.setStyleSheet("font-size:12px;")
        kinds.setText("<b style='color:#C4CEC9'>PDF</b> recompresses images, cleans unused data<br>"
                      "<b style='color:#C4CEC9'>Pictures</b> smarter JPG/PNG/WebP/HEIC encoding<br>"
                      "<b style='color:#C4CEC9'>Video</b> H.264 MP4 · <b style='color:#C4CEC9'>Audio</b> AAC M4A<br>"
                      "<b style='color:#C4CEC9'>Anything else</b> ZIP archive<br>"
                      "If a file can't get smaller, the original is kept.")
        lay.addWidget(kinds)
        self.total = label("")
        self.total.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}';font-size:15px;font-weight:600;"
                                 f"color:{theme.ACCENT};")
        lay.addWidget(self.total)
        self.level.changed.connect(lambda _: (self._sync(), self.remember()))
        self._sync()

    def _sync(self):
        self.level_note.setText(LEVEL_TEXT[self.level.value()])

    def options(self):
        return {"level": self.level.value()}

    def needs_ffmpeg(self):
        return any(compress.kind_of(it["src"]) in ("video", "audio") for it in self.items.values()
                   if it["status"] == "pending")

    def item_label(self, src):
        name, size = super().item_label(src)
        kind = {"pdf": "PDF", "image": "Picture", "video": "Video", "audio": "Audio", "zip": "File → ZIP"}[
            compress.kind_of(src)]
        return name, f"{kind} · {size}"

    def task(self, item, o):
        ctx = self.ctx

        def fn(progress, log, cancel):
            return compress.compress_file(item["src"], o["level"], o["folder"], ctx.ffmpeg, paths.ffprobe_path(),
                                          cancel, progress, log)
        return fn

    def describe(self, item, r):
        if r.note.startswith("already"):
            return f"Already as small as it gets · {mb(r.before)} · original kept", None
        return f"{mb(r.before)} → {mb(r.after)}  ·  −{r.saved_pct:.0f}%  ·  {Path(r.path).name}", r.path

    def update_summary(self):
        if not hasattr(self, "total"):
            return
        done = [it["result"] for it in self.items.values() if it["status"] == "done" and it["result"]]
        before = sum(r.before for r in done)
        after = sum(r.after for r in done)
        self.total.setText(f"Saved {mb(before - after)} so far" if done and before > after else "")


SESSION_INFO = {  # key: (menu title, icon, one-line description)
    "clip": ("Clip Video", "scissors", "Trim and download part of a video"),
    "audio": ("To MP3", "music", "Save the audio from YouTube, Instagram, X or SoundCloud"),
    "convert": ("Convert", "repeat", "Video, audio and pictures to other formats"),
    "resize": ("Resize", "resize", "Make pictures bigger or smaller"),
    "compress": ("Compress", "compress", "Shrink PDFs, pictures, video and more"),
}
SESSION_ORDER = ["clip", "audio", "convert", "resize", "compress"]
SESSION_ALIASES = {"images": "convert"}  # the old separate Images window now lives in Convert

TOOL_CLASSES = {"audio": AudioTool, "convert": ConvertTool, "resize": ResizeTool,
                "compress": CompressTool}
