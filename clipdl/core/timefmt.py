"""Time parsing and formatting helpers (no Qt imports)."""
from __future__ import annotations


def parse_time(text: str) -> float:
    """Parse ``90``, ``1:30``, ``1:02:30`` or ``1:30.5`` into seconds.

    Raises ValueError on anything else (empty, too many parts, negatives,
    non-numbers, minutes/seconds >= 60 in a multi-part value).
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty time")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"bad time: {text}")
    seconds = 0.0
    for i, p in enumerate(parts):
        p = p.strip()
        if not p:
            raise ValueError(f"bad time: {text}")
        try:
            v = float(p)
        except ValueError:
            raise ValueError(f"bad time: {text}") from None
        if v < 0:
            raise ValueError(f"negative time: {text}")
        # In "m:ss" or "h:mm:ss", every part after the first must be < 60.
        if i > 0 and v >= 60:
            raise ValueError(f"bad time: {text}")
        seconds = seconds * 60 + v
    return seconds


def fmt_time(sec: float, tenths: bool = False) -> str:
    """Format seconds as ``m:ss`` / ``h:mm:ss`` (optionally with ``.t``)."""
    if sec is None or sec < 0:
        sec = 0
    if tenths:
        total_tenths = int(round(sec * 10))
        whole, t = divmod(total_tenths, 10)
    else:
        whole, t = int(sec), 0
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    base = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    if tenths and t:
        base += f".{t}"
    return base


def fmt_duration_short(sec: float) -> str:
    """Compact duration for ETA-style labels, e.g. ``0:04`` or ``1:02:03``."""
    return fmt_time(max(0.0, sec or 0.0))
