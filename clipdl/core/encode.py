"""Output settings -> yt-dlp format selectors and ffmpeg arguments (no Qt imports).

Everything here is pure so it can be unit-tested without a network or a UI.
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from .settings import OutputSettings
from .timefmt import fmt_time

EXT = {"mp4": "mp4", "webm": "webm", "mov": "mov", "gif": "gif", "mp3": "mp3"}
CODEC_LABEL = {"h264": "H.264", "h265": "H.265", "vp9": "VP9"}


# ---------------------------------------------------------------- rules

def normalize(o: OutputSettings) -> OutputSettings:
    """Apply the format rules: WebM forces VP9, MOV has no VP9, GIF has no audio."""
    o = replace(o)
    if o.format == "webm":
        o.codec = "vp9"
    elif o.format == "mov" and o.codec == "vp9":
        o.codec = "h264"
    if o.format == "gif":
        o.audio = False
    return o


def codec_allowed(fmt: str, codec: str) -> bool:
    if fmt in ("gif", "mp3"):
        return False
    if fmt == "webm":
        return codec == "vp9"
    if fmt == "mov":
        return codec != "vp9"
    return True


def has_video(o: OutputSettings) -> bool:
    return o.format != "mp3"


def has_audio(o: OutputSettings) -> bool:
    o = normalize(o)
    return o.format == "mp3" or (o.format != "gif" and o.audio)


def target_height(o: OutputSettings, src_height: int | None) -> int | None:
    """Height to scale to, or None to keep the source."""
    if o.resolution == "src" or not has_video(o):
        return None
    h = int(o.resolution)
    if src_height and h >= src_height:
        return None
    return h


def target_fps(o: OutputSettings, src_fps: float | None) -> int | None:
    if o.fps == "src" or not has_video(o):
        return None
    f = int(o.fps)
    if src_fps and abs(f - src_fps) < 0.5:
        return None
    return f


ASPECT_LABEL = {"9:16": "Reels / TikTok / Shorts", "1:1": "Square post", "4:5": "Portrait post", "16:9": "Wide / YouTube"}
ASPECT_WIDTH_CAP = {"9:16": 1080, "1:1": 1080, "4:5": 1080, "16:9": 1920}  # never upscale past the source


def has_aspect(o: OutputSettings) -> bool:
    return getattr(o, "aspect", "src") != "src" and has_video(o)


def aspect_filters(o: OutputSettings) -> list[str]:
    """Crop to the chosen shape (centred unless the crop box was moved), then cap the width (a 9:16 reel ends up 1080x1920 at most)."""
    if not has_aspect(o):
        return []
    w, h = (int(x) for x in o.aspect.split(":"))
    a = f"({w}/{h})"
    cx = min(1.0, max(0.0, float(getattr(o, "crop_x", 0.5))))
    cy = min(1.0, max(0.0, float(getattr(o, "crop_y", 0.5))))
    f = [f"crop=w='trunc(min(iw\\,ih*{a})/2)*2':h='trunc(min(ih\\,iw/{a})/2)*2':x='(iw-ow)*{cx:.4f}':y='(ih-oh)*{cy:.4f}'"]
    if o.resolution == "src":  # an explicit resolution already sets the size
        f.append(f"scale=w='min(iw\\,{ASPECT_WIDTH_CAP[o.aspect]})':h=-2")
    return f


def crf_for(codec: str, quality: int) -> int:
    q = min(100, max(10, int(quality)))
    if codec == "vp9":
        return round(45 - (q - 10) / 90 * 25)
    base = round(34 - (q - 10) / 90 * 16)
    return base + 4 if codec == "h265" else base


def needs_reencode(o: OutputSettings, precise: bool, src_vcodec: str | None = None,
                   src_height: int | None = None, src_fps: float | None = None) -> bool:
    """Stream copy only for: fast cut, MP4, no scaling/fps change, H.264 out, H.264 in."""
    o = normalize(o)
    if precise or o.format != "mp4" or o.codec != "h264":
        return True
    if target_height(o, src_height) is not None or target_fps(o, src_fps) is not None or has_aspect(o):
        return True
    if src_vcodec is not None and not str(src_vcodec).startswith("avc1"):
        return True
    return False


# ---------------------------------------------------------------- yt-dlp

def ytdlp_format(o: OutputSettings, precise: bool, audio_lang: str | None = None) -> str:
    """Format selector used to pick the source streams for the clip.

    audio_lang pins the audio track (videos with dubbed / translated tracks); it falls back to yt-dlp's own pick,
    which prefers the track YouTube marks as original.
    """
    o = normalize(o)
    cap = f"[height<={int(o.resolution)}]" if o.resolution != "src" and has_video(o) else ""
    A = f'ba[language="{audio_lang}"]' if audio_lang else "ba"
    pin = audio_lang is not None
    if o.format == "mp3":
        return f"{A}/ba/b" if pin else "ba/b"
    want_audio = has_audio(o)
    if not precise and o.format == "mp4" and o.codec == "h264" and o.fps == "src":
        # try for an H.264 + AAC pair that can be stream-copied
        if want_audio:
            extra = f"bv*{cap}+ba/" if pin else ""
            return f"bv*[vcodec^=avc1]{cap}+{A}[ext=m4a]/bv*{cap}+{A}/{extra}b{cap}/b"
        return f"bv*[vcodec^=avc1]{cap}/bv*{cap}/b{cap}/b"
    if want_audio:
        extra = f"bv*{cap}+ba/" if pin else ""
        return f"bv*{cap}+{A}/{extra}b{cap}/b"
    return f"bv*{cap}/b{cap}/b"


# ---------------------------------------------------------------- ffmpeg

def video_filters(o: OutputSettings, src_height: int | None, src_fps: float | None) -> list[str]:
    f = []
    fps = target_fps(o, src_fps)
    if fps:
        f.append(f"fps={fps}")
    f += aspect_filters(o)
    h = target_height(o, src_height)
    if h:
        f.append(f"scale=-2:{h}:flags=lanczos" if o.format == "gif" else f"scale=-2:{h}")
    return f


def build_encode_args(o: OutputSettings, src_height: int | None = None,
                      src_fps: float | None = None) -> list[str]:
    """Codec/filter arguments for a re-encode (everything between inputs and output)."""
    o = normalize(o)
    abr = f"{int(o.audio_bitrate)}k"

    if o.format == "mp3":
        return ["-vn", "-c:a", "libmp3lame", "-b:a", abr]

    vf = video_filters(o, src_height, src_fps)

    if o.format == "gif":
        colors = max(32, min(256, round(32 + (o.quality - 10) / 90 * 224)))
        chain = ",".join(vf + ["split[a][b]"])
        graph = (f"[0:v]{chain};[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
                 f"[b][p]paletteuse=dither=bayer:bayer_scale=5[vout]")
        # the graph picks its own input and output, so callers must not add a video -map
        return ["-filter_complex", graph, "-map", "[vout]", "-an", "-loop", "0"]

    args: list[str] = []
    if vf:
        args += ["-vf", ",".join(vf)]

    crf = str(crf_for(o.codec, o.quality))
    if o.codec == "h264":
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", crf, "-pix_fmt", "yuv420p"]
    elif o.codec == "h265":
        args += ["-c:v", "libx265", "-preset", "medium", "-crf", crf, "-pix_fmt", "yuv420p",
                 "-tag:v", "hvc1", "-x265-params", "log-level=error"]
    else:  # vp9
        args += ["-c:v", "libvpx-vp9", "-crf", crf, "-b:v", "0", "-row-mt", "1",
                 "-deadline", "good", "-cpu-used", "4", "-pix_fmt", "yuv420p"]

    if has_audio(o):
        if o.format == "webm":
            args += ["-c:a", "libopus", "-b:a", abr]
        else:
            args += ["-c:a", "aac", "-b:a", abr]
    else:
        args += ["-an"]

    if o.format in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]
    return args


def copy_args(with_audio: bool) -> list[str]:
    args = ["-c", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart"]
    if not with_audio:
        args.insert(0, "-an")
    return args


# ---------------------------------------------------------------- estimates & labels

_BASE_MBPS = {2160: 20.0, 1440: 12.0, 1080: 8.0, 720: 5.0, 480: 2.5, 360: 1.4, 240: 0.8, 144: 0.4}
_CODEC_FACTOR = {"h264": 1.0, "h265": 0.6, "vp9": 0.65}


def _base_mbps(height: int) -> float:
    for h in sorted(_BASE_MBPS, reverse=True):
        if height >= h:
            return _BASE_MBPS[h]
    return 0.4


def estimate_size_mb(o: OutputSettings, clip_len: float, src_height: int | None = 1080,
                     src_fps: float | None = 30, src_tbr_kbps: float | None = None,
                     stream_copy: bool = False) -> float:
    """Rough output size in MB (shown with a ≈)."""
    o = normalize(o)
    length = max(0.1, float(clip_len))
    if stream_copy and src_tbr_kbps:
        return src_tbr_kbps * length / 8 / 1000
    abr_mbps = o.audio_bitrate / 1000
    if o.format == "mp3":
        return abr_mbps * length / 8
    h = target_height(o, src_height) or src_height or 1080
    fps = target_fps(o, src_fps) or src_fps or 30
    if o.format == "gif":
        return (h / 1080) ** 2 * fps * length * 0.09 * (0.5 + o.quality / 100)
    v = _base_mbps(h) * (fps / 30) ** 0.7 * _CODEC_FACTOR.get(o.codec, 1.0) * (0.35 + o.quality / 100 * 1.3)
    return (v + (abr_mbps if has_audio(o) else 0)) * length / 8


def summary_parts(o: OutputSettings, src_height: int | None, src_fps: float | None) -> list[str]:
    """Short labels like ['MP4', '1080p', '30 fps', 'H.264', 'Audio 192k']."""
    o = normalize(o)
    parts = [o.format.upper()]
    if o.format == "mp3":
        return parts + [f"{o.audio_bitrate} kbps"]
    h = target_height(o, src_height) or src_height
    fps = target_fps(o, src_fps) or (round(src_fps) if src_fps else None)
    if has_aspect(o):
        parts.append(o.aspect)
    if h:
        parts.append(f"{h}p")
    if fps:
        parts.append(f"{fps} fps")
    if o.format == "gif":
        return parts + ["No audio"]
    parts.append(CODEC_LABEL[o.codec])
    parts.append(f"Audio {o.audio_bitrate}k" if o.audio else "No audio")
    return parts


def clip_summary(start: float, end: float, o: OutputSettings, src_height, src_fps) -> str:
    return " · ".join([fmt_time(end - start, tenths=True)] + summary_parts(o, src_height, src_fps)[:4])


# ---------------------------------------------------------------- files

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def sanitize_filename(name: str, fallback: str = "clip") -> str:
    name = _BAD.sub("", name or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)[:120].strip()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if not name or name.upper() in reserved:
        return fallback
    return name


def unique_path(folder: Path | str, stem: str, ext: str) -> Path:
    folder = Path(folder)
    p = folder / f"{stem}.{ext}"
    n = 2
    while p.exists():
        p = folder / f"{stem} ({n}).{ext}"
        n += 1
    return p
