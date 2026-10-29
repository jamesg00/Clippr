"""Make files smaller: PDF (recompress images + clean structure), images, video, audio, else ZIP. No Qt imports."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import encode
from .clipper import ClipError, run_ffmpeg
from .images import IMAGE_IN, _open, ext_of, save_image

LEVELS = ("light", "balanced", "strong")
VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".3gp"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma", ".aiff", ".aif"}

# per level: (pdf image dpi, pdf jpeg quality, image quality, image max side, video crf, video max height, audio kbps)
PRESETS = {
    "light": (200, 85, 85, 4096, 26, None, 192),
    "balanced": (150, 75, 75, 2560, 28, 1080, 128),
    "strong": (100, 60, 60, 1600, 32, 720, 96),
}


@dataclass
class CompressResult:
    path: str
    before: int
    after: int
    kind: str  # pdf | image | video | audio | zip
    note: str = ""

    @property
    def saved_pct(self) -> float:
        return 0.0 if not self.before else max(0.0, (1 - self.after / self.before) * 100)


def kind_of(path: str) -> str:
    e = Path(path).suffix.lower()
    if e == ".pdf":
        return "pdf"
    if e in IMAGE_IN:
        return "image"
    if e in VIDEO_EXT:
        return "video"
    if e in AUDIO_EXT:
        return "audio"
    return "zip"


def _dest(src: Path, out_dir: str | None, ext: str) -> Path:
    folder = Path(out_dir) if out_dir else src.parent
    folder.mkdir(parents=True, exist_ok=True)
    return encode.unique_path(folder, src.stem + " (compressed)", ext)


def compress_pdf(src: str, dst: Path, level: str) -> str:
    try:
        import pymupdf
    except ImportError as e:
        raise ClipError("PDF compression needs PyMuPDF: pip install pymupdf") from e
    dpi, q, *_ = PRESETS[level]
    try:
        doc = pymupdf.open(src)
        if doc.needs_pass:
            raise ClipError("This PDF is password-protected.")
        if hasattr(doc, "rewrite_images"):
            doc.rewrite_images(dpi_threshold=dpi + 20, dpi_target=dpi, quality=q, lossy=True, lossless=True,
                               bitonal=True, color=True, gray=True, set_to_gray=False)
        doc.subset_fonts() if hasattr(doc, "subset_fonts") else None
        fd, tmp = tempfile.mkstemp(prefix=".clipdl-", suffix=".pdf", dir=dst.parent)
        os.close(fd)
        doc.save(tmp, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True, use_objstms=1)
        doc.close()
        os.replace(tmp, dst)
        return "images recompressed" if hasattr(pymupdf.Document, "rewrite_images") else "structure cleaned"
    except ClipError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ClipError("Couldn't compress this PDF.", str(e)) from e


def compress_image(src: str, dst: Path, level: str, fmt: str) -> str:
    q, max_side = PRESETS[level][2], PRESETS[level][3]
    im = _open(src)
    w, h = im.size
    note = ""
    if max(w, h) > max_side:
        f = max_side / max(w, h)
        im = im.resize((max(1, round(w * f)), max(1, round(h * f))))
        note = f"scaled to {im.size[0]}×{im.size[1]}"
    if fmt == "png" and level != "light":  # PNG can't get much smaller losslessly: quantize
        has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        im = im.convert("RGBA" if has_alpha else "RGB").quantize(colors=256 if level == "balanced" else 128,
                                                                 method=2 if has_alpha else 0, dither=1)
        note = (note + ", " if note else "") + "palette reduced"
    save_image(im, dst, fmt, q)
    return note


def compress_media(src: str, dst: Path, level: str, kind: str, ffmpeg: str, ffprobe: str | None,
                   cancel: threading.Event, tick) -> str:
    from .convert import probe
    info = probe(src, ffprobe, ffmpeg)
    _, _, _, _, crf, max_h, abr = PRESETS[level]
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats", "-i", src]
    if kind == "video":
        vf = []
        if max_h and info.height and info.height > max_h:
            vf.append(f"scale=-2:{max_h}")
        cmd += ["-map", "0:v:0", "-map", "0:a:0?"] + (["-vf", ",".join(vf)] if vf else [])
        cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", f"{abr}k", "-movflags", "+faststart"]
        note = f"H.264 CRF {crf}" + (f", {max_h}p" if vf else "")
    else:
        cmd += ["-vn", "-map", "0:a:0", "-c:a", "aac", "-b:a", f"{abr}k", "-movflags", "+faststart"]
        note = f"AAC {abr} kbps"
    run_ffmpeg(cmd + [str(dst)], info.duration or 1.0, cancel, tick, lambda s: None)
    return note


def compress_zip(src: str, dst: Path, level: str, cancel: threading.Event) -> str:
    lvl = {"light": 6, "balanced": 9, "strong": 9}[level]
    method = zipfile.ZIP_LZMA if level == "strong" else zipfile.ZIP_DEFLATED
    fd, tmp = tempfile.mkstemp(prefix=".clipdl-", suffix=".zip", dir=dst.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=method, compresslevel=None if method == zipfile.ZIP_LZMA else lvl) as z:
            z.write(src, arcname=Path(src).name)
        if cancel.is_set():
            raise ClipError("Cancelled")
        os.replace(tmp, dst)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return "LZMA zip" if method == zipfile.ZIP_LZMA else "zip"


def compress_file(src: str, level: str, out_dir: str | None, ffmpeg: str | None, ffprobe: str | None,
                  cancel: threading.Event, progress: Callable[[float | None, str], None],
                  log: Callable[[str], None]) -> CompressResult:
    if level not in LEVELS:
        raise ClipError(f"Unknown level: {level}")
    srcp = Path(src)
    if not srcp.is_file():
        raise ClipError("The file is gone.")
    before = srcp.stat().st_size
    kind = kind_of(src)
    progress(None, {"pdf": "Compressing PDF…", "image": "Compressing image…", "video": "Re-encoding video…",
                    "audio": "Re-encoding audio…", "zip": "Zipping…"}[kind])
    if kind in ("video", "audio") and not ffmpeg:
        raise ClipError("ffmpeg is needed to compress video and audio.")
    ext = {"pdf": "pdf", "video": "mp4", "audio": "m4a", "zip": "zip"}.get(kind) or ext_of(src)
    if kind == "image" and ext not in ("jpg", "png", "webp", "gif", "tiff", "heic"):
        ext = "png" if ext == "bmp" else "jpg"
    dst = _dest(srcp, out_dir, ext)
    if kind == "pdf":
        note = compress_pdf(src, dst, level)
    elif kind == "image":
        note = compress_image(src, dst, level, ext)
    elif kind in ("video", "audio"):
        def tick(frac, size, speed, ended):
            progress(min(99.0, frac * 100), f"Re-encoding {size / 1_000_000:.1f} MB" + (f" · {speed:.1f}×" if speed else ""))
        tmp_dir = Path(tempfile.mkdtemp(prefix=".clipdl-tmp-", dir=dst.parent))
        try:
            tmp_out = tmp_dir / dst.name
            note = compress_media(src, tmp_out, level, kind, ffmpeg, ffprobe, cancel, tick)
            os.replace(tmp_out, dst)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        note = compress_zip(src, dst, level, cancel)
    after = dst.stat().st_size
    if after >= before and kind != "zip":
        dst.unlink(missing_ok=True)
        progress(100.0, "Already as small as it gets")
        return CompressResult(str(srcp), before, before, kind, "already optimized, original kept")
    progress(100.0, "Done")
    return CompressResult(str(dst), before, after, kind, note)
