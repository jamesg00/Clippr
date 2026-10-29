"""Image conversion and resizing with Pillow. No Qt imports."""
from __future__ import annotations

import math
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from PIL import Image, ImageOps

from . import encode
from .clipper import ClipError

try:  # HEIC/HEIF (iPhone photos) when pillow-heif is installed
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF = True
except Exception:  # noqa: BLE001
    HEIF = False

IMAGE_OUT = ("png", "jpg", "webp", "bmp", "tiff", "gif", "ico") + (("heic",) if HEIF else ())
IMAGE_IN = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".ico", ".tga", ".ppm"} | \
    ({".heic", ".heif"} if HEIF else set())
PIL_NAME = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF", "gif": "GIF", "ico": "ICO",
            "heic": "HEIF"}
RESIZE_MODES = ("percent", "fit", "exact", "crop")


def _open(src: str) -> Image.Image:
    try:
        im = Image.open(src)
        im = ImageOps.exif_transpose(im)  # respect phone rotation
        im.load()
        return im
    except Exception as e:  # noqa: BLE001
        raise ClipError("Couldn't open this image.", str(e)) from e


def _prepare(im: Image.Image, fmt: str) -> Image.Image:
    """Convert colour modes to something the target format can store."""
    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    if fmt in ("jpg", "bmp"):
        if has_alpha:
            bg = Image.new("RGB", im.size, (255, 255, 255))
            rgba = im.convert("RGBA")
            bg.paste(rgba, mask=rgba.getchannel("A"))
            return bg
        return im.convert("RGB")
    if fmt == "gif":
        return im.convert("RGBA" if has_alpha else "RGB").convert("P", palette=Image.ADAPTIVE) if not has_alpha \
            else im.convert("RGBA")
    if fmt in ("png", "webp", "tiff", "ico", "heic"):
        if im.mode not in ("RGB", "RGBA", "L", "LA"):
            return im.convert("RGBA" if has_alpha else "RGB")
    return im


def save_image(im: Image.Image, dst: Path, fmt: str, quality: int = 85, keep_meta: bool = False,
               src_info: dict | None = None):
    im = _prepare(im, fmt)
    kw: dict = {}
    if fmt == "jpg":
        kw = {"quality": int(quality), "optimize": True, "progressive": True, "subsampling": 0 if quality >= 90 else 2}
    elif fmt == "webp":
        kw = {"quality": int(quality), "method": 6}
    elif fmt == "heic":
        kw = {"quality": int(quality)}
    elif fmt == "png":
        kw = {"optimize": True}
    elif fmt == "tiff":
        kw = {"compression": "tiff_deflate"}
    elif fmt == "ico":
        s = min(256, max(im.size))
        kw = {"sizes": [(x, x) for x in (16, 24, 32, 48, 64, 128, 256) if x <= s] or [(s, s)]}
    if keep_meta and src_info:
        if "exif" in src_info and fmt in ("jpg", "webp", "png", "tiff", "heic"):
            kw["exif"] = src_info["exif"]
        if "icc_profile" in src_info and fmt in ("jpg", "webp", "png", "tiff", "heic"):
            kw["icc_profile"] = src_info["icc_profile"]
    fd, tmp = tempfile.mkstemp(prefix=".clipdl-", suffix=f".{fmt}", dir=dst.parent)
    os.close(fd)
    try:
        im.save(tmp, PIL_NAME[fmt], **kw)
        os.replace(tmp, dst)
    except Exception as e:  # noqa: BLE001
        Path(tmp).unlink(missing_ok=True)
        raise ClipError(f"Couldn't save as {fmt.upper()}.", str(e)) from e


def _out_path(src: Path, out_dir: str | None, fmt: str, suffix: str = "") -> Path:
    folder = Path(out_dir) if out_dir else src.parent
    folder.mkdir(parents=True, exist_ok=True)
    stem = src.stem + suffix
    if not suffix and folder == src.parent and src.suffix.lower().lstrip(".") in (fmt, "jpeg" if fmt == "jpg" else fmt):
        stem += " (converted)"
    return encode.unique_path(folder, stem, fmt)


def ext_of(src: str) -> str:
    e = Path(src).suffix.lower().lstrip(".")
    heic = "heic" if HEIF else "jpg"
    return {"jpeg": "jpg", "jfif": "jpg", "tif": "tiff", "heic": heic, "heif": heic}.get(e, e)


def convert_image(src: str, fmt: str, out_dir: str | None = None, quality: int = 85, keep_meta: bool = False) -> str:
    if fmt not in IMAGE_OUT:
        raise ClipError(f"Unsupported image format: {fmt}")
    srcp = Path(src)
    im = _open(src)
    dst = _out_path(srcp, out_dir, fmt)
    save_image(im, dst, fmt, quality, keep_meta, im.info)
    return str(dst)


def target_size(w: int, h: int, mode: str, percent: float = 50, width: int | None = None,
                height: int | None = None, keep_aspect: bool = True) -> tuple[int, int]:
    """Pure size math for the resizer."""
    if mode == "percent":
        f = max(0.01, percent / 100)
        return max(1, round(w * f)), max(1, round(h * f))
    if mode == "fit":  # fit inside the box, never upscale-distort
        bw, bh = width or w, height or h
        f = min(bw / w, bh / h)
        return max(1, round(w * f)), max(1, round(h * f))
    if mode == "exact":
        if keep_aspect:
            if width:
                return width, max(1, round(h * width / w))
            if height:
                return max(1, round(w * height / h)), height
        return max(1, width or w), max(1, height or h)
    if mode == "crop":
        return max(1, width or w), max(1, height or h)
    raise ValueError(mode)


def resize_image(src: str, mode: str, percent: float = 50, width: int | None = None, height: int | None = None,
                 keep_aspect: bool = True, fmt: str = "same", quality: int = 90, out_dir: str | None = None,
                 suffix: str = "_resized", keep_meta: bool = False) -> tuple[str, tuple[int, int], tuple[int, int]]:
    """Returns (path, old_size, new_size)."""
    srcp = Path(src)
    im = _open(src)
    w, h = im.size
    tw, th = target_size(w, h, mode, percent, width, height, keep_aspect)
    out_fmt = ext_of(src) if fmt == "same" else fmt
    if out_fmt not in IMAGE_OUT:
        out_fmt = "png"
    if mode == "crop":
        out = ImageOps.fit(im, (tw, th), Image.LANCZOS, centering=(0.5, 0.5))
    else:
        out = im.resize((tw, th), Image.LANCZOS)
    dst = _out_path(srcp, out_dir, out_fmt, suffix or "_resized")
    save_image(out, dst, out_fmt, quality, keep_meta, im.info)
    return str(dst), (w, h), (tw, th)


# ---------------------------------------------------------------- free transform (the Resize editor)
@dataclass
class Transform:
    """Where the picture sits on the output canvas, Photoshop "Free Transform" style.

    Canvas pixels, origin top-left. (cx, cy) is the centre of the picture, sx / sy its scale, rot the clockwise
    rotation in degrees. Flips happen before rotation. bg: "transparent" or a "#rrggbb" fill for empty canvas.
    """
    canvas_w: int
    canvas_h: int
    cx: float
    cy: float
    sx: float = 1.0
    sy: float = 1.0
    rot: float = 0.0
    flip_h: bool = False
    flip_v: bool = False
    bg: str = "transparent"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transform":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    def copy(self) -> "Transform":
        return replace(self)


def initial_transform(iw: int, ih: int, mode: str = "percent", percent: float = 100, width: int | None = None,
                      height: int | None = None, keep_aspect: bool = True) -> Transform:
    """The transform the batch settings would produce, so the editor starts from what you'd get anyway."""
    tw, th = target_size(iw, ih, mode, percent, width, height, keep_aspect)
    if mode == "crop":
        s = max(tw / iw, th / ih)
        return Transform(tw, th, tw / 2, th / 2, s, s)
    return Transform(tw, th, tw / 2, th / 2, tw / iw, th / ih)


def fit_transform(t: Transform, iw: int, ih: int, cover: bool = False) -> Transform:
    """Scale (keeping proportions) and centre the picture so it fits inside / covers the canvas, rotation included."""
    a = math.radians(t.rot)
    bw = abs(iw * math.cos(a)) + abs(ih * math.sin(a))
    bh = abs(iw * math.sin(a)) + abs(ih * math.cos(a))
    s = (max if cover else min)(t.canvas_w / bw, t.canvas_h / bh)
    return replace(t, sx=s, sy=s, cx=t.canvas_w / 2, cy=t.canvas_h / 2)


MAX_SIDE = 30000


def render_transform(im: Image.Image, t: Transform) -> Image.Image:
    cw, ch = max(1, int(round(t.canvas_w))), max(1, int(round(t.canvas_h)))
    if cw > MAX_SIDE or ch > MAX_SIDE:
        raise ClipError(f"The canvas is too big (max {MAX_SIDE} px a side).")
    src = im.convert("RGBA")
    if t.flip_h:
        src = src.transpose(Image.FLIP_LEFT_RIGHT)
    if t.flip_v:
        src = src.transpose(Image.FLIP_TOP_BOTTOM)
    nw, nh = max(1, round(src.width * abs(t.sx))), max(1, round(src.height * abs(t.sy)))
    if nw > MAX_SIDE * 2 or nh > MAX_SIDE * 2:
        raise ClipError("The picture is scaled up too far.")
    if (nw, nh) != src.size:
        src = src.resize((nw, nh), Image.LANCZOS)
    r = t.rot % 360
    if abs(r) > 1e-6:
        quarter = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
        k = round(r)
        if abs(r - k) < 1e-6 and k in quarter:
            src = src.transpose(quarter[k])
        else:
            src = src.rotate(-r, resample=Image.BICUBIC, expand=True)
    layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    layer.paste(src, (int(round(t.cx - src.width / 2)), int(round(t.cy - src.height / 2))))
    if t.bg and t.bg != "transparent":
        base = Image.new("RGBA", (cw, ch), t.bg)
        return Image.alpha_composite(base, layer)
    return layer


def edit_image(src: str, t: Transform, fmt: str = "same", quality: int = 92, out_dir: str | None = None,
               suffix: str = "_edited", keep_meta: bool = False) -> tuple[str, tuple[int, int], tuple[int, int]]:
    """Render a free transform to a file. Returns (path, old_size, new_size)."""
    srcp = Path(src)
    im = _open(src)
    out = render_transform(im, t)
    out_fmt = ext_of(src) if fmt == "same" else fmt
    if out_fmt not in IMAGE_OUT:
        out_fmt = "png"
    if out_fmt in ("jpg", "bmp") and t.bg == "transparent":
        pass  # _prepare flattens onto white
    elif out_fmt not in ("png", "webp", "tiff", "gif", "ico", "heic") or t.bg != "transparent":
        out = out.convert("RGB") if out.getchannel("A").getextrema() == (255, 255) else out
    dst = _out_path(srcp, out_dir, out_fmt, suffix or "_edited")
    save_image(out, dst, out_fmt, quality, keep_meta, im.info)
    return str(dst), im.size, out.size
