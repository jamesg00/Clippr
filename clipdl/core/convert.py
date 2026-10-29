"""Convert local video/audio files to other formats with ffmpeg. No Qt imports."""
from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import encode
from .clipper import NO_WINDOW, ClipError, run_ffmpeg
from .settings import OutputSettings

VIDEO_OUT = ("mp4", "mkv", "webm", "mov", "avi", "gif")
AUDIO_OUT = ("mp3", "m4a", "wav", "flac", "ogg", "opus")
MEDIA_IN = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".3gp",
            ".gif", ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma", ".aiff", ".aif", ".alac"}


@dataclass
class MediaProbe:
    duration: float
    has_video: bool
    has_audio: bool
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    vcodec: str | None = None


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?: (Video|Audio): (\w+)(.*)")


def probe_with_ffmpeg(path: str, ffmpeg: str) -> MediaProbe:
    """Read duration / streams from `ffmpeg -i` (used when ffprobe isn't available)."""
    try:
        err = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True, timeout=30,
                             errors="replace", creationflags=NO_WINDOW).stderr
    except (OSError, subprocess.SubprocessError) as e:
        raise ClipError("Couldn't read this file.", str(e)) from e
    dur = 0.0
    m = _DUR_RE.search(err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    v = a = None
    for kind, codec, rest in _STREAM_RE.findall(err):
        if kind == "Video" and v is None and "attached pic" not in rest:
            v = (codec, rest)
        elif kind == "Audio" and a is None:
            a = codec
    if not v and not a:
        raise ClipError("This file has no video or audio.", err[-800:])
    w = h = fps = None
    if v:
        sz = re.search(r"\b(\d{2,5})x(\d{2,5})\b", v[1])
        if sz:
            w, h = int(sz.group(1)), int(sz.group(2))
        fr = re.search(r"([\d.]+) (?:fps|tbr)", v[1])
        if fr:
            fps = float(fr.group(1))
    return MediaProbe(dur, v is not None, a is not None, w, h, fps, v[0] if v else None)


def probe(path: str, ffprobe: str | None, ffmpeg: str | None = None) -> MediaProbe:
    if not ffprobe:
        if ffmpeg:
            return probe_with_ffmpeg(path, ffmpeg)
        raise ClipError("ffprobe wasn't found next to ffmpeg.")
    try:
        out = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                              "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
                              "-of", "json", path], capture_output=True, text=True, timeout=30,
                             creationflags=NO_WINDOW).stdout
        j = json.loads(out or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        raise ClipError("Couldn't read this file.", str(e)) from e
    streams = j.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not v and not a:
        raise ClipError("This file has no video or audio.")
    fps = None
    if v and v.get("r_frame_rate") and "/" in v["r_frame_rate"]:
        n, d = v["r_frame_rate"].split("/")
        fps = int(n) / int(d) if int(d) else None
    try:
        dur = float((j.get("format") or {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    return MediaProbe(dur, v is not None, a is not None, v and v.get("width"), v and v.get("height"), fps,
                      v and v.get("codec_name"))


def kind_of(fmt: str) -> str:
    return "audio" if fmt in AUDIO_OUT else "video"


def build_args(fmt: str, quality: int = 70, resolution="src", abr: int = 192, src: MediaProbe | None = None) -> list[str]:
    """ffmpeg arguments (between input and output) for converting to `fmt`."""
    sh = src.height if src else None
    sf = src.fps if src else None
    if fmt in ("mp4", "webm", "mov", "gif"):
        o = OutputSettings(format=fmt, resolution=resolution, quality=quality, audio=bool(src is None or src.has_audio),
                           audio_bitrate=abr, codec="vp9" if fmt == "webm" else "h264")
        args = encode.build_encode_args(o, sh, sf)
        if fmt != "gif":
            args = ["-map", "0:v:0?", "-map", "0:a:0?"] + args
        return args
    if fmt == "mkv":
        o = OutputSettings(format="mp4", resolution=resolution, quality=quality, audio_bitrate=abr)
        args = [a for a in encode.build_encode_args(o, sh, sf) if a not in ("-movflags", "+faststart")]
        return ["-map", "0:v:0?", "-map", "0:a:0?"] + args
    if fmt == "avi":
        q = max(2, min(31, round(31 - (quality - 10) / 90 * 29)))
        vf = encode.video_filters(OutputSettings(resolution=resolution), sh, None)
        return (["-map", "0:v:0?", "-map", "0:a:0?"] + (["-vf", ",".join(vf)] if vf else []) +
                ["-c:v", "mpeg4", "-q:v", str(q), "-c:a", "libmp3lame", "-b:a", f"{abr}k"])
    # audio outputs
    base = ["-vn", "-map", "0:a:0"]
    return base + {
        "mp3": ["-c:a", "libmp3lame", "-b:a", f"{abr}k"],
        "m4a": ["-c:a", "aac", "-b:a", f"{abr}k", "-movflags", "+faststart"],
        "wav": ["-c:a", "pcm_s16le"],
        "flac": ["-c:a", "flac", "-compression_level", "8"],
        "ogg": ["-c:a", "libvorbis", "-q:a", str(max(0, min(10, round(abr / 32))))],
        "opus": ["-c:a", "libopus", "-b:a", f"{min(abr, 256)}k"],
    }[fmt]


def convert_file(src: str, fmt: str, out_dir: str | None, ffmpeg: str, ffprobe: str | None,
                 cancel: threading.Event, progress: Callable[[float | None, str], None], log: Callable[[str], None],
                 quality: int = 70, resolution="src", abr: int = 192) -> str:
    srcp = Path(src)
    if not srcp.is_file():
        raise ClipError("The file is gone.")
    info = probe(src, ffprobe, ffmpeg)
    if kind_of(fmt) == "audio" and not info.has_audio:
        raise ClipError("This file has no audio to convert.")
    if kind_of(fmt) == "video" and not info.has_video:
        raise ClipError("This file has no video. Pick an audio format instead.")
    folder = Path(out_dir) if out_dir else srcp.parent
    folder.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".clipdl-tmp-", dir=folder))
    try:
        out_tmp = str(tmp / f"out.{fmt}")
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
               "-i", src] + build_args(fmt, quality, resolution, abr, info) + [out_tmp]
        progress(0.0, "Converting…")

        def tick(frac, size, speed, ended):
            sp = f" · {speed:.1f}×" if speed else ""
            progress(min(99.5, frac * 100), f"Converting {size / 1_000_000:.1f} MB{sp}")

        run_ffmpeg(cmd, info.duration or 1.0, cancel, tick, log)
        stem = srcp.stem if folder != srcp.parent or srcp.suffix.lower() != f".{fmt}" else srcp.stem + " (converted)"
        final = encode.unique_path(folder, stem, fmt)
        os.replace(out_tmp, final)
        progress(100.0, "Done")
        return str(final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
