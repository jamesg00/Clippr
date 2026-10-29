"""Turn things pasted or dropped from a browser into local image files. No Qt imports.

Handles:  http(s) image links · data: URIs · <img src> inside copied HTML · bare text that is a link.
"""
from __future__ import annotations

import base64
import html as _html
import io
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

from . import encode, paths
from .clipper import ClipError

MAX_BYTES = 80 * 1024 * 1024
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
_IMG_RE = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*(["'])(.*?)\1""", re.I | re.S)
_SRCSET_RE = re.compile(r"""<img\b[^>]*?\bsrcset\s*=\s*(["'])(.*?)\1""", re.I | re.S)
_EXT = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif", "BMP": "bmp", "TIFF": "tiff", "ICO": "ico",
        "HEIF": "heic", "AVIF": "avif"}


def pasted_dir() -> Path:
    d = paths.default_download_dir() / "Pasted images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_web_url(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith(("http://", "https://")) and " " not in t


def is_data_uri(text: str) -> bool:
    return (text or "").strip().startswith("data:image/")


def img_sources(html_text: str, base_url: str | None = None) -> list[str]:
    """Image addresses found in copied HTML, biggest srcset candidate first, de-duplicated."""
    out: list[str] = []
    for m in _SRCSET_RE.finditer(html_text or ""):
        best, best_w = None, -1.0
        for part in _html.unescape(m.group(2)).split(","):
            bits = part.strip().split()
            if not bits:
                continue
            w = 1.0
            if len(bits) > 1:
                try:
                    w = float(bits[1].rstrip("wx"))
                except ValueError:
                    pass
            if w > best_w:
                best, best_w = bits[0], w
        if best:
            out.append(best)
    for m in _IMG_RE.finditer(html_text or ""):
        out.append(_html.unescape(m.group(2)).strip())
    res = []
    for u in out:
        if base_url and not u.startswith(("http", "data:")):
            u = urllib.parse.urljoin(base_url, u)
        if u.startswith("//"):
            u = "https:" + u
        if (is_web_url(u) or is_data_uri(u)) and u not in res:
            res.append(u)
    return res


def _name_from_url(url: str) -> str:
    stem = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).stem
    return encode.sanitize_filename(stem[:60], time.strftime("Pasted %Y-%m-%d %H.%M.%S"))


def _save_bytes(data: bytes, stem: str, folder: Path) -> str:
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "PNG").upper()
            im.verify()
    except Exception as e:  # noqa: BLE001
        raise ClipError("That link isn't a picture (or the site blocked the download).", str(e)) from e
    ext = _EXT.get(fmt)
    if ext in (None, "avif"):  # formats the tools don't read directly are stored as PNG
        dst = encode.unique_path(folder, stem, "png")
        with Image.open(io.BytesIO(data)) as im:
            im.save(dst, "PNG")
        return str(dst)
    dst = encode.unique_path(folder, stem, ext)
    dst.write_bytes(data)
    return str(dst)


def decode_data_uri(uri: str, folder: Path | None = None) -> str:
    head, _, payload = uri.partition(",")
    data = base64.b64decode(payload) if ";base64" in head else urllib.parse.unquote_to_bytes(payload)
    return _save_bytes(data, time.strftime("Pasted %Y-%m-%d %H.%M.%S"), folder or pasted_dir())


def download_image(url: str, folder: Path | None = None, cancel=None, timeout: float = 25) -> str:
    """Download one picture to *folder* (default Downloads/Pasted images). Returns the saved path."""
    folder = folder or pasted_dir()
    if is_data_uri(url):
        return decode_data_uri(url, folder)
    if not is_web_url(url):
        raise ClipError("That isn't a web address.")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                                               "Referer": f"{urllib.parse.urlparse(url).scheme}://"
                                                          f"{urllib.parse.urlparse(url).netloc}/"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (user-supplied link)
            buf = io.BytesIO()
            while True:
                if cancel is not None and cancel():
                    raise ClipError("Cancelled.")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                buf.write(chunk)
                if buf.tell() > MAX_BYTES:
                    raise ClipError("That picture is too large to paste (over 80 MB).")
            final_url = r.geturl() or url
    except ClipError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ClipError("Couldn't download that picture.", str(e)) from e
    return _save_bytes(buf.getvalue(), _name_from_url(final_url), folder)
