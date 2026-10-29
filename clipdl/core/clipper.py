"""The clip pipeline: pick source streams, cut + encode with ffmpeg, report progress.

Main path (one pass): yt-dlp resolves the stream URLs, then ffmpeg seeks into
them and cuts/encodes just the selected range, writing ``-progress`` lines we
turn into live progress. Fallback: yt-dlp downloads the section itself
(``download_ranges``), then ffmpeg encodes the local file.

No Qt imports: callers pass callbacks and a ``threading.Event`` for cancel.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import encode
from .media_info import Stream, InfoError, fetch_info, selected_streams, friendly_error, ydl_base_opts
from .settings import OutputSettings


class Cancelled(Exception):
    pass


class ClipError(Exception):
    """User-facing failure; ``detail`` holds the raw text for the log."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


@dataclass
class ClipRequest:
    url: str
    start: float
    end: float
    output: OutputSettings
    precise: bool
    folder: str
    filename: str
    ffmpeg: str
    src_height: int | None = None
    src_fps: float | None = None
    cookies: str | None = None  # browser to borrow sign-in cookies from (Instagram / X)
    audio_lang: str | None = None  # pin this audio track (videos with dubbed / translated audio)
    local_stream: Stream | None = None  # a file on this computer: cut it directly, no download

    @property
    def length(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Progress:
    phase: str  # "preparing" | "downloading" | "encoding" | "finishing"
    percent: float = 0.0  # 0..100 overall
    out_bytes: int = 0
    est_total_bytes: int = 0
    speed_x: float | None = None  # encode speed vs realtime
    net_bytes_per_s: float | None = None  # only on the yt-dlp fallback path
    eta_s: float | None = None
    elapsed_s: float = 0.0
    stream_copy: bool = False
    indeterminate: bool = False


@dataclass
class ClipResult:
    path: str
    size_bytes: int
    elapsed_s: float
    stream_copy: bool
    summary: list[str] = field(default_factory=list)


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


# ---------------------------------------------------------------- command building (pure)

def _input_args(stream: Stream, start: float, length: float) -> list[str]:
    args: list[str] = []
    if stream.url.startswith("http"):
        hdrs = "".join(f"{k}: {v}\r\n" for k, v in (stream.headers or {}).items())
        if hdrs:
            args += ["-headers", hdrs]
        args += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]
    args += ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", stream.url]
    return args


def build_cut_command(ffmpeg: str, video: Stream | None, audio: Stream | None, start: float,
                      end: float, o: OutputSettings, precise: bool, out_path: str,
                      src_height: int | None = None, src_fps: float | None = None) -> tuple[list[str], bool]:
    """Return (argv, stream_copy)."""
    o = encode.normalize(o)
    length = max(0.05, end - start)
    want_audio = encode.has_audio(o)
    want_video = encode.has_video(o)
    src_vcodec = video.vcodec if video else None
    copy = not encode.needs_reencode(o, precise, src_vcodec, src_height or (video.height if video else None),
                                     src_fps or (video.fps if video else None))

    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]
    maps: list[str] = []
    idx = 0
    if want_video:
        if not video:
            raise ClipError("No video stream was found for this clip.")
        cmd += _input_args(video, start, length)
        if o.format != "gif":  # GIF's filter graph maps [0:v] itself
            maps += ["-map", f"{idx}:v:0"]
        if want_audio and audio is None:
            maps += ["-map", f"{idx}:a:0?"]
        idx += 1
    if want_audio and audio is not None:
        cmd += _input_args(audio, start, length)
        maps += ["-map", f"{idx}:a:0"]
        idx += 1
    elif want_audio and not want_video:  # mp3 from a muxed stream
        if not video:
            raise ClipError("No audio stream was found for this clip.")
        cmd += _input_args(video, start, length)
        maps += ["-map", "0:a:0"]
    cmd += maps
    if copy:
        cmd += encode.copy_args(with_audio=want_audio)
    else:
        cmd += encode.build_encode_args(o, src_height or (video.height if video else None),
                                        src_fps or (video.fps if video else None))
    cmd += ["-t", f"{length:.3f}", out_path]
    return cmd, copy


def build_encode_local_command(ffmpeg: str, src: str, o: OutputSettings, out_path: str,
                               copy: bool, src_height=None, src_fps=None) -> list[str]:
    o = encode.normalize(o)
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           "-i", src]
    if encode.has_video(o):
        if o.format != "gif" or copy:
            cmd += ["-map", "0:v:0"]
        if encode.has_audio(o):
            cmd += ["-map", "0:a:0?"]
    else:
        cmd += ["-map", "0:a:0"]
    cmd += encode.copy_args(encode.has_audio(o)) if copy else encode.build_encode_args(o, src_height, src_fps)
    return cmd + [out_path]


# ---------------------------------------------------------------- running ffmpeg

_TIME_KEYS = ("out_time_us", "out_time_ms")


def parse_progress_block(lines: list[str]) -> dict:
    d = {}
    for ln in lines:
        if "=" in ln:
            k, v = ln.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def _out_seconds(d: dict) -> float | None:
    for k in _TIME_KEYS:  # ffmpeg's out_time_ms is actually microseconds
        v = d.get(k)
        if v and v not in ("N/A",) and v.lstrip("-").isdigit():
            return max(0.0, int(v) / 1_000_000)
    v = d.get("out_time")
    if v and re.match(r"^\d+:\d\d:\d\d", v):
        h, m, s = v.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    return None


def run_ffmpeg(cmd: list[str], clip_len: float, cancel: threading.Event,
               on_tick: Callable[[float, int, float | None, bool], None],
               on_log: Callable[[str], None]) -> None:
    """Run ffmpeg; on_tick(fraction 0..1, out_bytes, speed_x, ended). Raises Cancelled/ClipError."""
    on_log("[ffmpeg] " + " ".join(_redact(cmd[1:])))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", bufsize=1,
                                creationflags=NO_WINDOW)
    except OSError as e:
        raise ClipError("Couldn't start ffmpeg.", str(e)) from e

    err_tail: deque[str] = deque(maxlen=40)

    def read_err():
        for ln in proc.stderr:
            ln = ln.rstrip()
            if ln:
                err_tail.append(ln)
                on_log("[ffmpeg] " + ln)

    t = threading.Thread(target=read_err, daemon=True)
    t.start()

    def killer():
        cancel.wait()
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    threading.Thread(target=killer, daemon=True).start()

    block: list[str] = []
    try:
        for ln in proc.stdout:
            ln = ln.strip()
            if not ln:
                continue
            block.append(ln)
            if ln.startswith("progress="):
                d = parse_progress_block(block)
                block = []
                sec = _out_seconds(d)
                frac = min(1.0, sec / clip_len) if (sec is not None and clip_len > 0) else 0.0
                size = d.get("total_size", "0")
                size = int(size) if size.isdigit() else 0
                sp = d.get("speed", "").rstrip("x").strip()
                try:
                    speed = float(sp) if sp and sp != "N/A" else None
                except ValueError:
                    speed = None
                on_tick(frac, size, speed, d.get("progress") == "end")
    finally:
        proc.wait()
        t.join(timeout=2)
    if cancel.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        detail = "\n".join(err_tail)
        raise ClipError(_ffmpeg_friendly(detail), detail)


def _redact(args: list[str]) -> list[str]:
    """Shorten stream URLs and drop header values in log lines."""
    out, skip = [], False
    for a in args:
        if skip:
            out.append("<headers>")
            skip = False
            continue
        if a == "-headers":
            out.append(a)
            skip = True
            continue
        if a.startswith("http"):
            out.append(a.split("?")[0][:48] + "…")
            continue
        out.append(a)
    return out


def _ffmpeg_friendly(detail: str) -> str:
    d = detail.lower()
    if "403" in d or "forbidden" in d:
        return "YouTube refused the stream (403)."
    if "no space left" in d:
        return "The disk is full."
    if "permission denied" in d:
        return "Can't write to this folder."
    if "unknown encoder" in d or "encoder not found" in d:
        return "Your ffmpeg build is missing an encoder for this format."
    if "connection" in d or "timed out" in d or "network" in d or "i/o error" in d:
        return "The connection dropped while downloading."
    return "ffmpeg failed to make the clip."


# ---------------------------------------------------------------- the job

class Clipper:
    """Runs one clip request. Call ``run()`` on a worker thread."""

    def __init__(self, req: ClipRequest, cancel: threading.Event,
                 on_progress: Callable[[Progress], None], on_log: Callable[[str], None],
                 resolve_streams: Callable[[ClipRequest], tuple] | None = None):
        self.req = req
        self.cancel = cancel
        self.on_progress = on_progress
        self.on_log = on_log
        self.resolve_streams = resolve_streams or self._resolve_streams
        self.t0 = time.monotonic()
        self._last_emit = 0.0
        self._last_pct = 0.0  # progress never goes backwards on screen

    # ---- helpers
    def _elapsed(self) -> float:
        return time.monotonic() - self.t0

    def _emit(self, p: Progress, force: bool = False):
        now = time.monotonic()
        p.percent = max(self._last_pct, min(100.0, p.percent))
        self._last_pct = p.percent
        if force or now - self._last_emit >= 0.05:
            self._last_emit = now
            p.elapsed_s = self._elapsed()
            self.on_progress(p)

    def _check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def _resolve_streams(self, req: ClipRequest):
        if req.local_stream is not None:
            return req.local_stream, None
        fmt = encode.ytdlp_format(req.output, req.precise, req.audio_lang)
        self.on_log(f"[youtube] Resolving streams ({fmt})")
        try:
            info = fetch_info(req.url, req.ffmpeg, fmt=fmt, cookies=req.cookies)
        except InfoError as e:
            raise ClipError(str(e)) from e
        v, a = selected_streams(info)
        if v:
            self.on_log(f"[info] Video: {v.vcodec} {v.height}p {v.fps or ''}fps")
        if a:
            self.on_log(f"[info] Audio: {a.acodec}")
        return v, a

    # ---- main
    def run(self) -> ClipResult:
        req = self.req
        if req.length < 0.1:
            raise ClipError("The clip is too short.")
        folder = Path(req.folder)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ClipError("Can't save to this folder.", str(e)) from e
        if not os.access(folder, os.W_OK):
            raise ClipError("Can't save to this folder.")

        o = encode.normalize(req.output)
        ext = encode.EXT[o.format]
        stem = encode.sanitize_filename(req.filename)
        est = int(encode.estimate_size_mb(o, req.length, req.src_height, req.src_fps) * 1_000_000)

        tmp = Path(tempfile.mkdtemp(prefix=".clipdl-tmp-", dir=folder))
        try:
            self._emit(Progress("preparing", 0, est_total_bytes=est, indeterminate=True), force=True)
            self._check()
            video, audio = self.resolve_streams(req)
            self._check()
            tmp_out = str(tmp / f"clip.{ext}")
            try:
                copy = self._direct(video, audio, o, tmp_out, est)
            except ClipError as e:
                if self.cancel.is_set():
                    raise Cancelled()
                if req.local_stream is not None:
                    raise
                self.on_log(f"[clip] Direct cut failed ({e}); falling back to yt-dlp section download")
                self._last_pct = 0.0
                copy = self._fallback(o, tmp, tmp_out, est)
            self._check()
            self._emit(Progress("finishing", 100, est_total_bytes=est, stream_copy=copy), force=True)
            final = encode.unique_path(folder, stem, ext)
            os.replace(tmp_out, final)
            size = final.stat().st_size
            self.on_log(f"[clip] Saved {final}")
            return ClipResult(str(final), size, self._elapsed(), copy,
                              encode.summary_parts(o, req.src_height, req.src_fps))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _direct(self, video, audio, o, tmp_out, est) -> bool:
        req = self.req
        cmd, copy = build_cut_command(req.ffmpeg, video, audio, req.start, req.end, o, req.precise, tmp_out,
                                      req.src_height, req.src_fps)
        self.on_log("[ffmpeg] " + ("Stream copy (no re-encode)" if copy else
                                   "Re-encoding: " + ", ".join(encode.summary_parts(o, req.src_height, req.src_fps)[1:])))
        phase = "downloading"

        def tick(frac, size, speed, ended):
            pct = 99.0 * frac if not ended else 99.5
            remaining = req.length * (1 - frac)
            eta = remaining / speed if speed and speed > 0 else None
            total = max(est, int(size / frac)) if frac > 0.15 and size else est
            self._emit(Progress("finishing" if (frac >= 0.995 or ended) else phase, pct, size, total,
                                speed_x=speed, eta_s=eta, stream_copy=copy))

        run_ffmpeg(cmd, req.length, self.cancel, tick, self.on_log)
        if not Path(tmp_out).is_file() or Path(tmp_out).stat().st_size == 0:
            raise ClipError("ffmpeg didn't produce a file.")
        return copy

    def _fallback(self, o, tmp: Path, tmp_out: str, est) -> bool:
        """yt-dlp downloads the section (0–70%), then ffmpeg encodes it (70–100%)."""
        import yt_dlp
        from yt_dlp.utils import DownloadError, download_range_func

        req = self.req
        src_tmpl = str(tmp / "src.%(ext)s")

        def hook(d):
            if self.cancel.is_set():
                raise Cancelled()
            if d.get("status") != "downloading":
                return
            done = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            fi, fc = d.get("fragment_index"), d.get("fragment_count")
            if total:
                frac = min(1.0, done / total)
            elif fi and fc:
                frac = min(1.0, fi / fc)
            else:
                frac = None
            self._emit(Progress("downloading", 70 * (frac or 0), done, est, net_bytes_per_s=d.get("speed"),
                                eta_s=d.get("eta"), indeterminate=frac is None))

        class Log:
            def debug(_, msg):
                if not msg.startswith("[debug]"):
                    self.on_log(msg)

            def info(_, msg):
                self.on_log(msg)

            def warning(_, msg):
                self.on_log("WARNING: " + msg)

            def error(_, msg):
                self.on_log(msg)

        opts = ydl_base_opts(req.ffmpeg, req.cookies)
        opts.update({
            "format": encode.ytdlp_format(o, req.precise, req.audio_lang),
            "outtmpl": src_tmpl,
            "download_ranges": download_range_func(None, [(req.start, req.end)]),
            "force_keyframes_at_cuts": req.precise,
            "merge_output_format": "mkv",
            "progress_hooks": [hook],
            "logger": Log(),
            "quiet": False,
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([req.url])
        except Cancelled:
            raise
        except DownloadError as e:
            if self.cancel.is_set():
                raise Cancelled()
            raise ClipError(friendly_error(str(e)), str(e)) from e
        self._check()
        srcs = [p for p in tmp.glob("src.*") if p.suffix not in (".part", ".ytdl")]
        if not srcs:
            raise ClipError("The download didn't produce a file.")
        src = str(srcs[0])
        copy = not encode.needs_reencode(o, req.precise, None, req.src_height, req.src_fps) and not req.precise
        cmd = build_encode_local_command(req.ffmpeg, src, o, tmp_out, copy, req.src_height, req.src_fps)

        def tick(frac, size, speed, ended):
            remaining = req.length * (1 - frac)
            self._emit(Progress("encoding", 70 + 29.5 * frac, size, est, speed_x=speed,
                                eta_s=(remaining / speed) if speed else None, stream_copy=copy))

        run_ffmpeg(cmd, req.length, self.cancel, tick, self.on_log)
        return copy


def new_job_id() -> str:
    return uuid.uuid4().hex[:8]
