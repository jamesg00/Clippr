"""Backend for the four tool sessions (To MP3, Convert, Resize, Compress) in the QML UI.

It reuses the existing core code unchanged (audio_dl, convert, images, compress) and runs one queue per session on
the shared thread pool through workers.jobs.FuncJob. QML only talks to this object (context property `tools`).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import (Property, QAbstractListModel, QModelIndex, QObject, QThreadPool, QUrl, Qt, Signal, Slot)
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage
from PySide6.QtQuick import QQuickImageProvider

from ..core import audio_dl, compress, convert, images, media_info, paths
from ..workers.jobs import FuncJob

KEYS = {"mp3": "audio", "convert": "convert", "resize": "resize", "compress": "compress"}

DEFAULTS = {
    "audio": {"format": "mp3", "bitrate": 320, "cover": True, "tags": True, "trim": True},
    "convert": {"format": "mp4", "resolution": "src", "quality": 70, "abr": 192, "img_format": "png",
                "img_quality": 90, "meta": False},
    "resize": {"mode": "percent", "percent": 50, "width": 1280, "height": 720, "keep_aspect": True,
               "format": "same", "suffix": "_resized"},
    "compress": {"level": "balanced"},
}
TEXT_KEYS = {"format", "resolution", "img_format", "mode", "suffix", "level"}
INT_KEYS = {"bitrate", "quality", "abr", "img_quality", "percent", "width", "height"}
BOOL_KEYS = {"cover", "tags", "meta", "keep_aspect", "trim"}

ROLES = ["iid", "name", "sub", "status", "pct", "text", "resultText", "resultPath", "kind"]


def mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB" if n >= 1_000_000 else f"{max(1, n // 1000)} KB"


class ItemModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []

    def roleNames(self):
        return {Qt.UserRole + i: r.encode() for i, r in enumerate(ROLES)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.rows)):
            return None
        i = role - Qt.UserRole
        return self.rows[index.row()].get(ROLES[i]) if 0 <= i < len(ROLES) else None

    def add(self, row: dict):
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append(row)
        self.endInsertRows()

    def find(self, iid: int) -> int:
        for i, r in enumerate(self.rows):
            if r["iid"] == iid:
                return i
        return -1

    def update(self, iid: int, **kw):
        i = self.find(iid)
        if i < 0:
            return
        self.rows[i].update(kw)
        self.dataChanged.emit(self.index(i), self.index(i))

    def remove(self, iid: int):
        i = self.find(iid)
        if i < 0:
            return
        self.beginRemoveRows(QModelIndex(), i, i)
        del self.rows[i]
        self.endRemoveRows()

    def clear_finished(self):
        for r in [r for r in self.rows if r["status"] in ("done", "error")]:
            self.remove(r["iid"])


def media_kind(src: str) -> str:
    ext = Path(src).suffix.lower()
    if ext == ".gif":
        try:
            from PIL import Image
            with Image.open(src) as im:
                return "media" if getattr(im, "n_frames", 1) > 1 else "image"
        except Exception:  # noqa: BLE001
            return "image"
    return "image" if ext in images.IMAGE_IN else "media"


class PreviewProvider(QQuickImageProvider):
    """Serves the picture being edited in Resize to QML as image://preview/<n>."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.image = QImage(2, 2, QImage.Format.Format_RGBA8888)
        self.image.fill(0)

    def requestImage(self, id, size, requestedSize):  # noqa: A002, N802
        return self.image


def load_preview(path: str, max_side: int = 1800) -> tuple[QImage, int, int]:
    """(preview image, original width, original height). Pillow so HEIC and EXIF rotation work."""
    from PIL import Image, ImageOps
    with Image.open(path) as im0:
        im = ImageOps.exif_transpose(im0)
        iw, ih = im.size
        im = im.convert("RGBA")
        if max(iw, ih) > max_side:
            f = max_side / max(iw, ih)
            im = im.resize((max(1, round(iw * f)), max(1, round(ih * f))), Image.BILINEAR)
        data = im.tobytes("raw", "RGBA")
        q = QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()
    return q, iw, ih


class ToolsBackend(QObject):
    sessionChanged = Signal()
    optionsChanged = Signal()
    queueChanged = Signal()
    toast = Signal(str)
    editorChanged = Signal()

    def __init__(self, cfg, ffmpeg: str | None, save_cb, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.ffmpeg = ffmpeg
        self._save = save_cb
        self.pool = QThreadPool.globalInstance()
        self._session = "mp3"
        self._models = {k: ItemModel(self) for k in KEYS}
        self._next_id = 1
        self._job = None
        self._job_sid = ""
        self._job_iid = 0
        self._cancelling = False
        self._extras: dict[int, dict] = {}
        self._opts: dict[str, dict] = {}
        for k, key in KEYS.items():
            o = dict(DEFAULTS[key])
            saved = cfg.tools.get(key) or {}
            for name, default in DEFAULTS[key].items():
                v = saved.get(name, default)
                if name in BOOL_KEYS:
                    v = bool(v)
                elif name in INT_KEYS:
                    try:
                        v = int(v)
                    except (TypeError, ValueError):
                        v = default
                else:
                    v = str(v)
                o[name] = v
            self._opts[k] = o
        meta = cfg.tools.get("_tools") or {}
        self._to_originals = {k: bool(meta.get("orig_" + k, k != "mp3")) for k in KEYS}
        self._folder = str(meta.get("folder") or "")
        # Resize editor
        self.provider = PreviewProvider()
        self._sel = -1
        self._edits: dict[int, dict] = {}
        self._previews: dict[str, tuple] = {}
        self._prev_token = 0

    # ----------------------------------------------------------- session
    @Slot(str)
    def setSession(self, sid: str):
        if sid in KEYS and sid != self._session:
            self._session = sid
            self.sessionChanged.emit()
            self.optionsChanged.emit()
            self.queueChanged.emit()
            self._ensure_selection()

    @Property(str, notify=sessionChanged)
    def session(self) -> str:
        return self._session

    @Property(QObject, notify=sessionChanged)
    def items(self):
        return self._models[self._session]

    @Property(bool, notify=queueChanged)
    def running(self) -> bool:
        return self._job is not None and self._job_sid == self._session

    @Property(bool, notify=queueChanged)
    def busyElsewhere(self) -> bool:
        return self._job is not None and self._job_sid != self._session

    def _count(self, status: str, sid: str | None = None) -> int:
        return sum(1 for r in self._models[sid or self._session].rows if r["status"] == status)

    @Property(int, notify=queueChanged)
    def pendingCount(self) -> int:
        return self._count("pending") + self._count("error")

    @Property(int, notify=queueChanged)
    def doneCount(self) -> int:
        return self._count("done")

    @Property(int, notify=queueChanged)
    def totalCount(self) -> int:
        return len(self._models[self._session].rows)

    @Property(bool, notify=queueChanged)
    def canStart(self) -> bool:
        return self._job is None and self.pendingCount > 0 and not self._needs_missing_ffmpeg()

    @Property(str, notify=queueChanged)
    def summaryText(self) -> str:
        n, done, run = self.totalCount, self.doneCount, self.running
        if n == 0:
            return ""
        if self._needs_missing_ffmpeg():
            return "ffmpeg wasn't found. Put ffmpeg.exe in the app's bin folder or on PATH, then restart."
        if run:
            return f"Working on {self._count('running') + self._count('pending')} of {n}…"
        if done == n:
            return f"All {n} finished."
        parts = [f"{self._count('pending') + self._count('error')} ready"]
        if done:
            parts.append(f"{done} finished")
        return " · ".join(parts)

    @Property(str, notify=queueChanged)
    def startLabel(self) -> str:
        return {"mp3": "Download audio", "convert": "Convert", "resize": "Resize", "compress": "Compress"}[self._session]

    def _needs_ffmpeg(self, sid: str) -> bool:
        rows = [r for r in self._models[sid].rows if r["status"] in ("pending", "error")]
        if sid == "mp3":
            return bool(rows)
        if sid == "convert":
            return any(r["kind"] == "media" for r in rows)
        if sid == "compress":
            return any(compress.kind_of(r["src"]) in ("video", "audio") for r in rows)
        return False

    def _needs_missing_ffmpeg(self) -> bool:
        return not self.ffmpeg and self._needs_ffmpeg(self._session)

    # ----------------------------------------------------------- options
    @Property("QVariantMap", notify=optionsChanged)
    def options(self) -> dict:
        return dict(self._opts[self._session])

    @Slot(str, "QVariant")
    def setOption(self, name: str, value):
        o = self._opts[self._session]
        if name not in o:
            return
        if name in BOOL_KEYS:
            value = bool(value)
        elif name in INT_KEYS:
            try:
                value = int(round(float(value)))
            except (TypeError, ValueError):
                return
        else:
            value = str(value)
        if o[name] == value:
            return
        o[name] = value
        self.cfg.tools[KEYS[self._session]] = dict(o)
        self.optionsChanged.emit()
        if self._session == "resize":
            self.editorChanged.emit()
        self._save()

    @Property(bool, notify=optionsChanged)
    def toOriginals(self) -> bool:
        return self._to_originals[self._session]

    @Slot(bool)
    def setToOriginals(self, on: bool):
        self._to_originals[self._session] = bool(on)
        self._persist_meta()
        self.optionsChanged.emit()

    @Property(str, notify=optionsChanged)
    def folder(self) -> str:
        return self._folder or self.cfg.save_folder or str(paths.default_download_dir())

    @Property(str, notify=optionsChanged)
    def folderLabel(self) -> str:
        if self._session != "mp3" and self._to_originals[self._session]:
            return "Next to the originals"
        return self.folder

    @Slot()
    def chooseFolder(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(None, "Save to", self.folder)
        if d:
            self._folder = os.path.normpath(d)
            if self._session != "mp3":
                self._to_originals[self._session] = False
            self._persist_meta()
            self.optionsChanged.emit()

    def _persist_meta(self):
        meta = {"orig_" + k: v for k, v in self._to_originals.items()}
        meta["folder"] = self._folder
        self.cfg.tools["_tools"] = meta
        self._save()

    @Slot()
    def openFolder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder))

    def _out_dir(self, sid: str) -> str | None:
        if sid != "mp3" and self._to_originals[sid]:
            return None
        return self.folder

    # ----------------------------------------------------------- adding things
    def _new_row(self, **kw) -> dict:
        row = {"iid": self._next_id, "name": "", "sub": "", "status": "pending", "pct": 0.0, "text": "",
               "resultText": "", "resultPath": "", "kind": "media", "src": ""}
        row.update(kw)
        self._next_id += 1
        return row

    def _accepts(self, sid: str, p: Path) -> bool:
        ext = p.suffix.lower()
        if sid == "convert":
            return ext in convert.MEDIA_IN or ext in images.IMAGE_IN
        if sid == "resize":
            return ext in images.IMAGE_IN
        return True

    def _label(self, sid: str, src: str) -> str:
        try:
            size = mb(os.path.getsize(src))
        except OSError:
            return ""
        if sid == "compress":
            kind = {"pdf": "PDF", "image": "Picture", "video": "Video", "audio": "Audio",
                    "zip": "File → ZIP"}[compress.kind_of(src)]
            return f"{kind} · {size}"
        if sid in ("convert", "resize") and media_kind(src) == "image":
            try:
                from PIL import Image
                with Image.open(src) as im:
                    return f"{im.size[0]}×{im.size[1]} · {size}"
            except Exception:  # noqa: BLE001
                pass
        return size

    @Slot("QVariantList")
    def addPaths(self, items):
        sid = self._session
        if sid == "mp3":
            self.addLinks("\n".join(str(i) for i in items))
            return
        files: list[str] = []
        for it in items:
            s = str(it)
            local = QUrl(s).toLocalFile() if s.startswith("file:") else s
            p = Path(local)
            if p.is_dir():
                for sub in sorted(p.rglob("*")):
                    if sub.is_file() and self._accepts(sid, sub):
                        files.append(str(sub))
            elif p.is_file() and self._accepts(sid, p):
                files.append(str(p))
        have = {r["src"] for r in self._models[sid].rows if r["status"] != "done"}
        added = 0
        for f in files:
            if f in have:
                continue
            have.add(f)
            kind = media_kind(f) if sid == "convert" else "media"
            self._models[sid].add(self._new_row(name=Path(f).name, sub=self._label(sid, f), src=f, kind=kind))
            added += 1
        if not added and items:
            self.toast.emit("Nothing here this tool can use." if not files else "Those are already in the list.")
        self.queueChanged.emit()
        self._ensure_selection()

    @Slot(str)
    def addLinks(self, text: str):
        if self._session != "mp3":
            return
        urls = re.findall(r"https?://\S+", text or "")
        if not urls and text and text.strip():
            urls = [text.strip()]
        have = {r["src"] for r in self._models["mp3"].rows if r["status"] != "done"}
        added = bad = 0
        for u in urls:
            clean, _ = media_info.clean_audio_url(u.strip())
            if not clean:
                bad += 1
                continue
            if clean in have:
                continue
            have.add(clean)
            short = re.sub(r"^https?://(www\.)?", "", clean)
            self._models["mp3"].add(self._new_row(name=short, sub="Waiting", src=clean, kind="link"))
            added += 1
        if bad:
            self.toast.emit("That isn't a YouTube, Instagram, X or SoundCloud link." if not added
                            else f"Skipped {bad} link{'s' if bad > 1 else ''} that aren't supported.")
        self.queueChanged.emit()

    @Slot()
    def pasteLinks(self):
        self.addLinks(QGuiApplication.clipboard().text())

    @Slot()
    def browse(self):
        from PySide6.QtWidgets import QFileDialog
        sid = self._session
        if sid == "mp3":
            return
        flt = {"convert": "Media and pictures (*)", "resize": "Pictures (" + " ".join("*" + e for e in sorted(images.IMAGE_IN)) + ")",
               "compress": "All files (*)"}[sid]
        files, _ = QFileDialog.getOpenFileNames(None, "Choose files", "", flt)
        if files:
            self.addPaths(files)

    @Slot(int)
    def remove(self, iid: int):
        if self._job is not None and self._job_iid == iid:
            return
        self._models[self._session].remove(iid)
        self._edits.pop(iid, None)
        self.queueChanged.emit()
        self._ensure_selection()

    @Slot()
    def clearFinished(self):
        self._models[self._session].clear_finished()
        self.queueChanged.emit()
        self._ensure_selection()

    # ----------------------------------------------------------- running
    @Slot()
    def start(self):
        if self._job is None and self.canStart:
            for r in self._models[self._session].rows:
                if r["status"] == "error":
                    self._models[self._session].update(r["iid"], status="pending", text="", pct=0.0)
            self._cancelling = False
            self._run_next(self._session)

    @Slot()
    def cancel(self):
        if self._job is not None:
            self._cancelling = True
            self._job.cancel()

    def _run_next(self, sid: str):
        row = next((r for r in self._models[sid].rows if r["status"] == "pending"), None)
        if row is None:
            self.queueChanged.emit()
            return
        o = dict(self._opts[sid])
        fn = self._make_task(sid, row, o)
        job = FuncJob(str(row["iid"]), fn)
        job.signals.progress.connect(self._on_progress)
        job.signals.done.connect(lambda payload, s=sid, i=row["iid"]: self._on_done(s, i, payload))
        job.signals.failed.connect(lambda msg, detail, s=sid, i=row["iid"]: self._on_failed(s, i, msg))
        job.signals.cancelled.connect(lambda s=sid, i=row["iid"]: self._on_cancelled(s, i))
        self._job, self._job_sid, self._job_iid = job, sid, row["iid"]
        self._models[sid].update(row["iid"], status="running", pct=-1.0, text="Starting…")
        self.queueChanged.emit()
        self.pool.start(job)

    def _make_task(self, sid: str, row: dict, o: dict):
        src, out = row["src"], self._out_dir(sid)
        ff, fp = self.ffmpeg, paths.ffprobe_path()
        cookies = self.cfg.cookies
        if sid == "mp3":
            extra: dict = {}
            self._extras[row["iid"]] = extra

            def fn(progress, log, cancel):
                return audio_dl.download_audio(src, o["format"], o["bitrate"], out, ff, cancel, progress, log,
                                               cookies=cookies, cover=o["cover"], metadata=o["tags"],
                                               trim_lead=o["trim"], extra=extra)
        elif sid == "convert":
            if row["kind"] == "image":
                def fn(progress, log, cancel):
                    progress(None, "Converting…")
                    return images.convert_image(src, o["img_format"], out, o["img_quality"], o["meta"])
            else:
                res = o["resolution"] if o["resolution"] == "src" else int(o["resolution"])

                def fn(progress, log, cancel):
                    return convert.convert_file(src, o["format"], out, ff, fp, cancel, progress, log,
                                                o["quality"], res, o["abr"])
        elif sid == "resize":
            w = o["width"] or None
            h = o["height"] or None
            edit = self._edits.get(row["iid"])
            tr = images.Transform.from_dict(self._clean_t(edit)) if edit else None

            def fn(progress, log, cancel):
                if tr is not None:
                    progress(None, "Rendering…")
                    return images.edit_image(src, tr, o["format"], 92, out, o["suffix"] or "_resized")
                progress(None, "Resizing…")
                return images.resize_image(src, o["mode"], o["percent"], w, h, o["keep_aspect"], o["format"], 92,
                                           out, o["suffix"] or "_resized")
        else:
            def fn(progress, log, cancel):
                return compress.compress_file(src, o["level"], out, ff, fp, cancel, progress, log)
        return fn

    def _on_progress(self, payload):
        _token, pct, text = payload
        if self._job is None:
            return
        self._models[self._job_sid].update(self._job_iid, pct=-1.0 if pct is None else float(pct), text=text or "")

    def _finish(self, sid: str):
        self._job = None
        self._job_iid = 0
        if self._cancelling or self._count("pending", sid) == 0:
            self._cancelling = False
            self.queueChanged.emit()
        else:
            self._run_next(sid)

    def _describe(self, sid: str, result) -> tuple[str, str]:
        try:
            if sid == "resize":
                path, old, new = result
                return f"{old[0]}×{old[1]} → {new[0]}×{new[1]} · {Path(path).name}", path
            if sid == "compress":
                if result.note.startswith("already"):
                    return f"Already as small as it gets · {mb(result.before)} · original kept", ""
                return (f"{mb(result.before)} → {mb(result.after)} · −{result.saved_pct:.0f}% · "
                        f"{Path(result.path).name}", result.path)
            p = Path(result)
            size = mb(p.stat().st_size)
            return (f"Saved {p.name} · {size}" if sid == "mp3" else f"→ {p.name} · {size}"), str(p)
        except Exception:  # noqa: BLE001
            return "Done", ""

    def _on_done(self, sid: str, iid: int, payload):
        _token, result = payload
        text, path = self._describe(sid, result)
        cut = (self._extras.pop(iid, None) or {}).get("trimmed")
        if cut:
            text += f" · cut {cut:.2f} s from the start"
        self._models[sid].update(iid, status="done", pct=100.0, text="", resultText=text, resultPath=path)
        self._finish(sid)

    def _on_failed(self, sid: str, iid: int, msg: str):
        self._models[sid].update(iid, status="error", pct=0.0, text=msg)
        self._finish(sid)

    def _on_cancelled(self, sid: str, iid: int):
        self._models[sid].update(iid, status="pending", pct=0.0, text="Cancelled")
        self._cancelling = True
        self._finish(sid)

    # ----------------------------------------------------------- results
    @Slot(int)
    def reveal(self, iid: int):
        for sid in KEYS:
            i = self._models[sid].find(iid)
            if i >= 0 and self._models[sid].rows[i]["resultPath"]:
                paths.reveal(self._models[sid].rows[i]["resultPath"])
                return

    @Slot(int)
    def openResult(self, iid: int):
        for sid in KEYS:
            i = self._models[sid].find(iid)
            if i >= 0 and self._models[sid].rows[i]["resultPath"]:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self._models[sid].rows[i]["resultPath"]))
                return

    # ----------------------------------------------------------- Resize: the picture editor
    @staticmethod
    def _clean_t(d: dict) -> dict:
        t = dict(d)
        t["canvas_w"] = max(1, int(round(float(t.get("canvas_w", 1)))))
        t["canvas_h"] = max(1, int(round(float(t.get("canvas_h", 1)))))
        for k in ("cx", "cy", "sx", "sy", "rot"):
            t[k] = float(t.get(k, 0.0 if k != "sx" and k != "sy" else 1.0))
        t["flip_h"], t["flip_v"] = bool(t.get("flip_h")), bool(t.get("flip_v"))
        t["bg"] = str(t.get("bg") or "transparent")
        return t

    def _preview(self, src: str):
        if src not in self._previews:
            try:
                self._previews[src] = load_preview(src)
            except Exception:  # noqa: BLE001
                self._previews[src] = (None, 1, 1)
        return self._previews[src]

    def _sel_row(self):
        if self._session != "resize":
            return None
        m = self._models["resize"]
        i = m.find(self._sel)
        return m.rows[i] if i >= 0 else None

    def _ensure_selection(self):
        if self._session != "resize":
            self.editorChanged.emit()
            return
        rows = self._models["resize"].rows
        if self._sel_row() is None:
            pend = [r for r in rows if r["status"] != "done"] or rows
            self._sel = pend[0]["iid"] if pend else -1
            self._load_selected()
        self.editorChanged.emit()

    def _load_selected(self):
        r = self._sel_row()
        if r is None:
            return
        img, _iw, _ih = self._preview(r["src"])
        if img is not None:
            self.provider.image = img
            self._prev_token += 1

    def _batch_t(self, iw: int, ih: int) -> dict:
        o = self._opts["resize"]
        m, w, h = o["mode"], o["width"] or None, o["height"] or None
        if m == "fit":
            w, h = w or 100000, h or 100000
        elif m == "crop":
            w = w or h
            h = h or w
        return images.initial_transform(iw, ih, m, o["percent"], w, h, o["keep_aspect"]).to_dict()

    @Property("QVariantMap", notify=editorChanged)
    def editor(self) -> dict:
        r = self._sel_row()
        if r is None:
            return {}
        img, iw, ih = self._preview(r["src"])
        if img is None:
            return {"id": r["iid"], "ok": False, "name": r["name"]}
        edit = self._edits.get(r["iid"])
        try:
            t = self._clean_t(edit) if edit else self._batch_t(iw, ih)
        except Exception:  # noqa: BLE001
            return {"id": r["iid"], "ok": False, "name": r["name"]}
        return {"id": r["iid"], "ok": True, "name": r["name"], "token": self._prev_token, "iw": iw, "ih": ih,
                "t": t, "edited": edit is not None, "locked": r["status"] == "running"}

    @Property(int, notify=editorChanged)
    def selectedId(self) -> int:
        return self._sel if self._sel_row() is not None else -1

    @Slot(int)
    def selectItem(self, iid: int):
        if self._session != "resize" or iid == self._sel:
            return
        self._sel = iid
        self._load_selected()
        self.editorChanged.emit()

    def _edit_text(self, t: dict) -> str:
        return f"Custom · {t['canvas_w']}×{t['canvas_h']} px" + (f" · {t['rot']:.0f}°" if abs(t["rot"]) > 0.05 else "")

    def _mark_edit(self, iid: int, t: dict | None):
        m = self._models["resize"]
        i = m.find(iid)
        if i < 0:
            return
        row = m.rows[i]
        if row["status"] == "pending":
            row.setdefault("sub0", row["sub"])
            m.update(iid, sub=self._edit_text(t) if t else row["sub0"])

    @Slot(int, "QVariantMap")
    def setEdit(self, iid: int, t):
        """The editor changed the transform for a picture (from a gesture or a field)."""
        r = self._sel_row()
        if r is None or r["iid"] != iid or r["status"] == "running":
            return
        t = self._clean_t(dict(t))
        self._edits[iid] = t
        self._mark_edit(iid, t)
        self.queueChanged.emit()  # the summary line and the Start button follow

    @Slot(int)
    def resetEdit(self, iid: int):
        self._edits.pop(iid, None)
        self._mark_edit(iid, None)
        self.queueChanged.emit()
        self.editorChanged.emit()

    @Slot(int)
    def applyEditToAll(self, iid: int):
        """Copy this picture's canvas and placement to every other waiting picture."""
        cur_t = self._edits.get(iid)
        r = self._sel_row()
        if cur_t is None or r is None:
            return
        _, iw, _ih = self._preview(r["src"])
        n = 0
        for row in self._models["resize"].rows:
            if row["iid"] == iid or row["status"] != "pending":
                continue
            img, w2, h2 = self._preview(row["src"])
            if img is None:
                continue
            s = cur_t["sx"] * iw / w2
            t2 = dict(cur_t)
            t2["sx"] = s
            t2["sy"] = s * (cur_t["sy"] / cur_t["sx"] if cur_t["sx"] else 1)
            self._edits[row["iid"]] = t2
            self._mark_edit(row["iid"], t2)
            n += 1
        self.toast.emit(f"Applied to {n} more picture{'s' if n != 1 else ''}.")
        self.queueChanged.emit()

    @Slot()
    def shutdown(self):
        if self._job is not None:
            self._cancelling = True
            self._job.cancel()
        self.pool.waitForDone(3000)
