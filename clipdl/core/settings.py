"""Settings model + JSON persistence (no Qt imports)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths

SETTINGS_VERSION = 1

FORMATS = ("mp4", "webm", "mov", "gif", "mp3")
RESOLUTIONS = ("src", 1080, 720, 480, 360)
FRAME_RATES = ("src", 60, 30, 24, 15)
CODECS = ("h264", "h265", "vp9")
ASPECTS = ("src", "9:16", "1:1", "4:5", "16:9")  # frame shape: Reels / Square / Portrait post / Wide
AUDIO_BITRATES = (128, 192, 320)


@dataclass
class OutputSettings:
    format: str = "mp4"
    resolution: object = "src"  # "src" or int height
    fps: object = "src"  # "src" or int
    codec: str = "h264"
    quality: int = 70  # 10..100
    audio: bool = True
    audio_bitrate: int = 192
    aspect: str = "src"  # "src" keeps the video's own shape; others crop to it
    crop_x: float = 0.5  # where the crop sits when the video is wider than the shape (0 = left edge, 1 = right edge)
    crop_y: float = 0.5  # ...and when it is taller (0 = top, 1 = bottom)

    def is_default(self) -> bool:
        return self == OutputSettings()


@dataclass
class AppSettings:
    version: int = SETTINGS_VERSION
    save_folder: str = field(default_factory=lambda: str(paths.default_download_dir()))
    precise: bool = True  # frame-accurate cut
    output: OutputSettings = field(default_factory=OutputSettings)
    glass: bool | None = None  # legacy (v2.0); migrated to `appearance`
    appearance: str | None = None  # "solid" | "frosted" | "clear"; None = per-OS default on first run
    opacity: float = 0.45  # window tint opacity for frosted/clear (0.15..1.0)
    cookies: str | None = None  # browser to borrow sign-in cookies from (Instagram / X)
    volume: float = 0.8
    loop: bool = False
    window: list | None = None  # [x, y, w, h]
    tools: dict = field(default_factory=dict)  # per-tool remembered options


def _coerce_output(d: dict) -> OutputSettings:
    o = OutputSettings()
    if not isinstance(d, dict):
        return o
    fmt = d.get("format")
    if fmt in FORMATS:
        o.format = fmt
    res = d.get("resolution")
    if res in RESOLUTIONS:
        o.resolution = res
    fps = d.get("fps")
    if fps in FRAME_RATES:
        o.fps = fps
    codec = d.get("codec")
    if codec in CODECS:
        o.codec = codec
    q = d.get("quality")
    if isinstance(q, (int, float)) and not isinstance(q, bool):
        o.quality = int(min(100, max(10, round(q / 5) * 5)))
    if isinstance(d.get("audio"), bool):
        o.audio = d["audio"]
    if d.get("aspect") in ASPECTS:
        o.aspect = d["aspect"]
    for k in ("crop_x", "crop_y"):
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            setattr(o, k, float(min(1.0, max(0.0, v))))
    if d.get("audio_bitrate") in AUDIO_BITRATES:
        o.audio_bitrate = d["audio_bitrate"]
    return o


def from_dict(d: dict) -> AppSettings:
    s = AppSettings()
    if not isinstance(d, dict):
        return s
    # (future) migrations keyed on d.get("version") go here.
    if isinstance(d.get("save_folder"), str) and d["save_folder"].strip():
        s.save_folder = d["save_folder"]
    if isinstance(d.get("precise"), bool):
        s.precise = d["precise"]
    s.output = _coerce_output(d.get("output", {}))
    if isinstance(d.get("glass"), bool):
        s.glass = d["glass"]
    if d.get("appearance") in ("solid", "frosted", "clear"):
        s.appearance = d["appearance"]
    elif isinstance(d.get("glass"), bool):  # migrate 2.0 setting
        s.appearance = "frosted" if d["glass"] else "solid"
    op = d.get("opacity")
    if isinstance(op, (int, float)) and not isinstance(op, bool):
        s.opacity = float(min(1.0, max(0.15, op)))
    if d.get("cookies") in ("firefox", "chrome", "edge", "brave", "opera", "vivaldi"):
        s.cookies = d["cookies"]
    if isinstance(d.get("tools"), dict):
        s.tools = {k: v for k, v in d["tools"].items() if isinstance(k, str) and isinstance(v, dict)}
    v = d.get("volume")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        s.volume = float(min(1.0, max(0.0, v)))
    if isinstance(d.get("loop"), bool):
        s.loop = d["loop"]
    w = d.get("window")
    if isinstance(w, list) and len(w) == 4 and all(isinstance(x, int) for x in w):
        s.window = w
    return s


def to_dict(s: AppSettings) -> dict:
    d = asdict(s)
    d["version"] = SETTINGS_VERSION
    return d


def settings_file() -> Path:
    return paths.settings_dir() / "settings.json"


def load(path: Path | None = None) -> AppSettings:
    path = path or settings_file()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return from_dict(json.load(f))
    except (OSError, ValueError):
        return AppSettings()


def save(s: AppSettings, path: Path | None = None) -> None:
    path = path or settings_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(to_dict(s), f, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass  # settings are a convenience; never crash over them
