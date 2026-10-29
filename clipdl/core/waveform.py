"""Audio peaks for the trim track (no Qt imports)."""
from __future__ import annotations

import subprocess
import sys
import threading

import numpy as np

from .media_info import Stream

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
SAMPLE_RATE = 2000
MAX_SECONDS = 3 * 3600  # skip waveform for very long videos


def peaks_from_pcm(pcm: bytes, buckets: int) -> list[float]:
    """Mono s16le PCM -> `buckets` peak values in 0..1 (normalized to the 98th percentile)."""
    data = np.frombuffer(pcm[: len(pcm) - (len(pcm) % 2)], dtype="<i2").astype(np.float32)
    if data.size == 0 or buckets <= 0:
        return [0.0] * max(0, buckets)
    edges = np.linspace(0, data.size, buckets + 1).astype(int)
    out = np.zeros(buckets, dtype=np.float32)
    absd = np.abs(data)
    for i in range(buckets):
        a, b = edges[i], edges[i + 1]
        if b > a:
            out[i] = absd[a:b].max()
    ref = np.percentile(out, 98) or out.max() or 1.0
    out = np.clip(out / ref, 0, 1)
    return [float(x) for x in out]


def compute_peaks(ffmpeg: str, stream: Stream, duration: float, cancel: threading.Event,
                  buckets: int = 400) -> list[float] | None:
    """Decode the stream to low-rate mono PCM and reduce to peaks. None if skipped/failed/cancelled."""
    if not ffmpeg or not stream or duration > MAX_SECONDS:
        return None
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error"]
    if stream.url.startswith("http"):
        hdrs = "".join(f"{k}: {v}\r\n" for k, v in (stream.headers or {}).items())
        if hdrs:
            cmd += ["-headers", hdrs]
    cmd += ["-i", stream.url, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except OSError:
        return None
    chunks = []
    try:
        while True:
            if cancel.is_set():
                proc.kill()
                return None
            b = proc.stdout.read(65536)
            if not b:
                break
            chunks.append(b)
    finally:
        proc.wait()
    if proc.returncode != 0 or not chunks:
        return None
    return peaks_from_pcm(b"".join(chunks), buckets)
