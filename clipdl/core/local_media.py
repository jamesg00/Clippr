"""Open a video (or audio) file from this computer so a part of it can be clipped, like a link."""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .media_info import Stream, VideoInfo

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
MEDIA_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".mpg", ".mpeg", ".ts", ".3gp",
              ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


class LocalError(Exception):
    pass


def is_media(path: str) -> bool:
    return Path(path).suffix.lower() in MEDIA_EXTS


def _run(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=30,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LocalError("Couldn't read this file.") from e
    return (p.stderr or "") + (p.stdout or "")


def _thumb(ffmpeg: str, path: Path, duration: float) -> str | None:
    folder = Path(tempfile.gettempdir()) / "clippr-thumbs"
    try:
        folder.mkdir(exist_ok=True)
        st = path.stat()
        key = hashlib.md5(f"{path}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:16]
        out = folder / f"{key}.jpg"
        if not out.is_file():
            at = min(max(duration * 0.1, 0.0), 5.0)
            _run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", str(path),
                  "-frames:v", "1", "-vf", "scale=640:-2", str(out)])
        return out.as_uri() if out.is_file() and out.stat().st_size > 0 else None
    except OSError:
        return None


def probe(path: str, ffmpeg: str) -> VideoInfo:
    p = Path(path)
    if not p.is_file():
        raise LocalError("That file doesn't exist any more.")
    if not ffmpeg:
        raise LocalError("ffmpeg is missing, so local files can't be opened.")
    text = _run([ffmpeg, "-hide_banner", "-i", str(p)])
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not m:
        raise LocalError("This doesn't look like a video or audio file.")
    duration = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    if duration < 0.2:
        raise LocalError("This file is too short to clip.")
    vm = re.search(r"Stream #\d+:\d+[^\n]*?: Video: (\w+)[^\n]*?, (\d{2,5})x(\d{2,5})", text)
    am = re.search(r"Stream #\d+:\d+[^\n]*?: Audio: (\w+)", text)
    if "attached pic" in text and vm and text.count("Video:") == 1:
        vm = None  # cover art in an mp3 is not a video
    fps_m = re.search(r"(\d+(?:\.\d+)?) fps", text) if vm else None
    if not vm and not am:
        raise LocalError("This doesn't look like a video or audio file.")
    height = int(vm[3]) if vm else None
    fps = float(fps_m[1]) if fps_m else None
    stream = Stream(url=str(p), vcodec=vm[1] if vm else None, acodec=am[1] if am else None,
                    height=height, fps=fps, ext=p.suffix.lstrip(".").lower())
    return VideoInfo(
        id=str(p), title=p.stem, channel="On this computer", duration=duration,
        thumbnail=_thumb(ffmpeg, p, duration) if vm else None, webpage_url=str(p),
        heights=[height] if height else [], max_height=height, fps=fps,
        preview_video=stream if vm else None, preview_audio=None,
        waveform_audio=stream if am else None)
