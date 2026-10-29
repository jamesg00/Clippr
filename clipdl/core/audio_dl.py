"""Link -> audio file (MP3/M4A/WAV/FLAC/Opus) via yt-dlp + ffmpeg. No Qt imports."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

from . import encode
from .clipper import NO_WINDOW, Cancelled, ClipError
from .media_info import guess_audio_lang, clean_audio_url, friendly_error, ydl_base_opts

AUDIO_FORMATS = ("mp3", "m4a", "wav", "flac", "opus")
BITRATES = (128, 192, 256, 320)
LOSSLESS = ("wav", "flac")
THUMB_OK = ("mp3", "m4a", "flac")  # cover art embedding that works with plain ffmpeg


# ---------------------------------------------------------------- cut the junk at the start
SILENCE_DB = -50      # quieter than this counts as silence
MIN_GAP = 0.12        # a silence must last this long to split the audio into pieces
MIN_BODY = 1.5        # a piece shorter than this is a stray blip, not the song
SCAN_SECONDS = 20.0   # only the first seconds are searched
_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def find_real_start(path: str, ffmpeg: str, cancel: threading.Event | None = None) -> float:
    """Where the song really begins, in seconds (0.0 = nothing to cut).

    Splits the first seconds into pieces separated by silence and skips every piece shorter than MIN_BODY,
    i.e. the little detached blips that sit in front of many downloads, as well as plain leading silence.
    """
    try:
        err = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-t", str(SCAN_SECONDS), "-i", path, "-af",
                              f"silencedetect=noise={SILENCE_DB}dB:d={MIN_GAP}", "-f", "null", "-"],
                             capture_output=True, text=True, errors="replace", timeout=90,
                             creationflags=NO_WINDOW).stderr
    except (OSError, subprocess.SubprocessError):
        return 0.0
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    # silences as (start, end); a silence still open at the end of the scan has end = None
    silences: list[list] = []
    for line in err.splitlines():
        m = _SIL_START.search(line)
        if m:
            silences.append([max(0.0, float(m.group(1))), None])
            continue
        m = _SIL_END.search(line)
        if m and silences and silences[-1][1] is None:
            silences[-1][1] = float(m.group(1))
    # sound pieces are what lies between the silences
    pieces: list[tuple[float, float | None]] = []
    pos = 0.0
    for s, e in silences:
        if s - pos > 0.005:
            pieces.append((pos, s))
        if e is None:  # silence runs to the end of the scan: nothing after it
            pos = None
            break
        pos = e
    if pos is not None:
        pieces.append((pos, None))  # sound that runs on past the scan
    for start, end in pieces:
        if end is None or end - start >= MIN_BODY:
            return start if start >= 0.03 else 0.0
    return 0.0  # no clear song start in the scan window: leave it alone


_AUDIO_ARGS = {
    "mp3": lambda br: ["-c:a", "libmp3lame", "-b:a", f"{br}k"],
    "m4a": lambda br: ["-c:a", "aac", "-b:a", f"{br}k"],
    "opus": lambda br: ["-c:a", "libopus", "-b:a", f"{min(br, 256)}k"],
    "wav": lambda br: ["-c:a", "pcm_s16le"],
    "flac": lambda br: ["-c:a", "flac", "-compression_level", "8"],
}


def trim_start_of(path: Path, start: float, fmt: str, bitrate: int, ffmpeg: str, log) -> bool:
    """Rewrite `path` without its first `start` seconds, to the sample. Tags and cover art are kept.
    Returns False (file untouched) if ffmpeg couldn't do it."""
    out = path.with_name(path.stem + ".trim" + path.suffix)
    base = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(path),
            "-ss", f"{start:.3f}", "-map_metadata", "0"]
    tail = _AUDIO_ARGS[fmt](bitrate) + [str(out)]
    for maps in (["-map", "0:a", "-map", "0:v?", "-c:v", "copy"], ["-map", "0:a"]):  # second try: without cover art
        try:
            r = subprocess.run(base + maps + tail, capture_output=True, text=True, errors="replace", timeout=600,
                               creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as e:
            log(f"[trim] {e}")
            return False
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            os.replace(out, path)
            return True
        log("[trim] " + (r.stderr or "").strip()[-300:])
        out.unlink(missing_ok=True)
    return False


def download_audio(url: str, fmt: str, bitrate: int, folder: str, ffmpeg: str, cancel: threading.Event,
                   progress: Callable[[float | None, str], None], log: Callable[[str], None],
                   cookies: str | None = None, cover: bool = True, metadata: bool = True,
                   allow_files: bool = False, trim_lead: bool = False,
                   extra: dict | None = None) -> str:
    """Download the best audio of `url` and convert it. Returns the saved path."""
    if fmt not in AUDIO_FORMATS:
        raise ClipError(f"Unsupported audio format: {fmt}")
    if not allow_files:
        clean, _ = clean_audio_url(url)
        if not clean:
            raise ClipError("That isn't a YouTube, Instagram, X or SoundCloud link.")
        url = clean
    folder_p = Path(folder)
    try:
        folder_p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ClipError("Can't save to this folder.", str(e)) from e
    tmp = Path(tempfile.mkdtemp(prefix=".clipdl-tmp-", dir=folder_p))

    import yt_dlp
    from yt_dlp.utils import DownloadError

    def hook(d):
        if cancel.is_set():
            raise Cancelled()
        if d.get("status") == "downloading":
            done = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                sp = d.get("speed")
                extra = f" · {sp / 1_000_000:.1f} MB/s" if sp else ""
                progress(min(85.0, 85.0 * done / total), f"Downloading {done / 1_000_000:.1f} MB{extra}")
            else:
                progress(None, "Downloading…")
        elif d.get("status") == "finished":
            progress(86.0, "Converting…")

    def pp_hook(d):
        if cancel.is_set():
            raise Cancelled()
        if d.get("status") == "started":
            name = d.get("postprocessor", "")
            label = {"ExtractAudio": f"Converting to {fmt.upper()}…", "FFmpegMetadata": "Adding tags…",
                     "EmbedThumbnail": "Adding cover art…"}.get(name, "Processing…")
            progress(min(98.0, 88.0 + 4 * ["ExtractAudio", "FFmpegMetadata", "EmbedThumbnail"].index(name))
                     if name in ("ExtractAudio", "FFmpegMetadata", "EmbedThumbnail") else None, label)

    class Log:
        def debug(_, m):
            if not m.startswith("[debug]"):
                log(m)

        def info(_, m):
            log(m)

        def warning(_, m):
            log("WARNING: " + m)

        def error(_, m):
            log(m)

    pps = [{"key": "FFmpegExtractAudio", "preferredcodec": fmt,
            "preferredquality": "0" if fmt in LOSSLESS else str(int(bitrate))}]
    if metadata:
        pps.append({"key": "FFmpegMetadata", "add_metadata": True})
    want_cover = cover and fmt in THUMB_OK
    if want_cover:
        pps.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
    opts = ydl_base_opts(ffmpeg, cookies)
    opts.update({
        "format": "ba/b",
        "outtmpl": str(tmp / "%(title).120B.%(ext)s"),
        "postprocessors": pps,
        "writethumbnail": want_cover,
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "logger": Log(),
        "quiet": False,
        "enable_file_urls": allow_files,
    })
    try:
        progress(None, "Finding the audio…")
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                raw = None
                try:  # look first, so a video with dubbed / translated tracks keeps its original audio
                    raw = ydl.extract_info(url, download=False, process=False)
                except DownloadError:
                    raw = None
                lang = guess_audio_lang(raw.get("formats") or []) if isinstance(raw, dict) else None
                if lang:
                    log(f"[audio] Several audio tracks; using the original ({lang})")
                    opts["format"] = f'ba[language="{lang}"]/ba/b'
                    with yt_dlp.YoutubeDL(opts) as ydl2:
                        ydl2.process_ie_result(raw, download=True)
                elif isinstance(raw, dict):
                    ydl.process_ie_result(raw, download=True)
                else:
                    ydl.download([url])
        except Cancelled:
            raise
        except DownloadError as e:
            if cancel.is_set():
                raise Cancelled()
            # cover art can fail on odd thumbnails: retry once without it
            if want_cover and ("thumbnail" in str(e).lower() or "embed" in str(e).lower()):
                log("[audio] Cover art failed, retrying without it")
                for f in tmp.iterdir():
                    f.unlink(missing_ok=True)
                opts["postprocessors"] = [p for p in pps if p["key"] != "EmbedThumbnail"]
                opts["writethumbnail"] = False
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
            else:
                raise ClipError(friendly_error(str(e)), str(e)) from e
        if cancel.is_set():
            raise Cancelled()
        outs = sorted(tmp.glob(f"*.{fmt}"), key=lambda p: p.stat().st_size, reverse=True)
        if not outs:
            raise ClipError("The conversion didn't produce a file.")
        src = outs[0]
        if trim_lead:
            progress(97.0, "Finding the start of the song…")
            try:
                begin = find_real_start(str(src), ffmpeg, cancel)
                if begin > 0:
                    progress(98.0, "Cutting the lead-in…")
                    if trim_start_of(src, begin, fmt, bitrate, ffmpeg, log):
                        log(f"[audio] Cut {begin:.2f}s from the start")
                        if extra is not None:
                            extra["trimmed"] = begin
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001 - never lose the download over this
                log(f"[audio] Start trim skipped: {e}")
        final = encode.unique_path(folder_p, encode.sanitize_filename(src.stem, "audio"), fmt)
        os.replace(src, final)
        progress(100.0, "Done")
        return str(final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
