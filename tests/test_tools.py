"""Tool back-ends: audio download, media convert, image convert/resize, compressor (real files, no network)."""
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipdl.core import audio_dl, compress, convert, images  # noqa: E402
from clipdl.core.clipper import ClipError  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ff = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg not installed")


def noop(*a, **k):
    pass


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("m")
    vid = d / "clip video.mp4"
    aud = d / "song.wav"
    base = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run(base + ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=4", "-f", "lavfi", "-i",
                           "sine=frequency=440:duration=4", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12",
                           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-shortest", str(vid)], check=True)
    subprocess.run(base + ["-f", "lavfi", "-i", "sine=frequency=330:duration=4", str(aud)], check=True)
    return {"video": vid, "audio": aud, "dir": d}


def probe(p):
    return convert.probe(str(p), FFPROBE)


# ------------------------------------------------------------ convert
@needs_ff
@pytest.mark.parametrize("fmt", convert.VIDEO_OUT + convert.AUDIO_OUT)
def test_convert_video_to_everything(media, tmp_path, fmt):
    out = convert.convert_file(str(media["video"]), fmt, str(tmp_path), FFMPEG, FFPROBE, threading.Event(),
                               noop, noop, quality=60, resolution=480 if fmt in convert.VIDEO_OUT else "src")
    p = probe(out)
    assert Path(out).suffix == f".{fmt}"
    assert abs(p.duration - 4) < 0.3 or fmt == "gif"
    if fmt in convert.VIDEO_OUT:
        assert p.has_video and p.height == 480
    else:
        assert p.has_audio and not p.has_video
    assert not list(tmp_path.glob(".clipdl-tmp-*"))


@needs_ff
def test_convert_audio_only_to_video_is_refused(media, tmp_path):
    with pytest.raises(ClipError, match="no video"):
        convert.convert_file(str(media["audio"]), "mp4", str(tmp_path), FFMPEG, FFPROBE, threading.Event(), noop, noop)


@needs_ff
def test_convert_same_folder_names(media):
    out = convert.convert_file(str(media["video"]), "mp4", None, FFMPEG, FFPROBE, threading.Event(), noop, noop)
    assert Path(out).name == "clip video (converted).mp4"
    Path(out).unlink()


# ------------------------------------------------------------ audio download (file:// stands in for a link)
@needs_ff
@pytest.mark.parametrize("fmt", audio_dl.AUDIO_FORMATS)
def test_download_audio_formats(media, tmp_path, fmt):
    steps = []
    out = audio_dl.download_audio(media["video"].resolve().as_uri(), fmt, 192, str(tmp_path), FFMPEG,
                                  threading.Event(), lambda p, t: steps.append((p, t)), noop,
                                  cover=False, allow_files=True)
    p = probe(out)
    assert Path(out).suffix == f".{fmt}" and p.has_audio and not p.has_video
    assert steps[-1][0] == 100.0
    assert not list(tmp_path.glob(".clipdl-tmp-*"))


def test_download_audio_rejects_other_sites(tmp_path):
    with pytest.raises(ClipError, match="YouTube, Instagram, X or SoundCloud"):
        audio_dl.download_audio("https://vimeo.com/1", "mp3", 192, str(tmp_path), "ffmpeg", threading.Event(),
                                noop, noop)


# ------------------------------------------------------------ images
@pytest.fixture
def pics(tmp_path):
    rgba = Image.new("RGBA", (1200, 800), (40, 200, 140, 128))
    for x in range(0, 1200, 40):
        for y in range(0, 800, 40):
            rgba.putpixel((x, y), (255, 0, 0, 255))
    p1 = tmp_path / "alpha.png"
    rgba.save(p1)
    p2 = tmp_path / "photo.jpg"
    Image.effect_noise((1600, 1200), 60).convert("RGB").save(p2, quality=98)
    return p1, p2


@pytest.mark.parametrize("fmt", images.IMAGE_OUT)
def test_convert_image_all_formats(pics, tmp_path, fmt):
    out_dir = tmp_path / "out"
    for src in pics:
        out = images.convert_image(str(src), fmt, str(out_dir), quality=80)
        assert Path(out).suffix == f".{fmt}"
        with Image.open(out) as im:
            assert im.size[0] > 0


def test_jpg_flattens_alpha_on_white(pics, tmp_path):
    out = images.convert_image(str(pics[0]), "jpg", str(tmp_path / "o"))
    with Image.open(out) as im:
        r, g, b = im.getpixel((5, 5))
        assert im.mode == "RGB" and r > 120  # blended toward white, not black


@pytest.mark.parametrize("args,expected", [
    (("percent", 50), (600, 400)),
    (("fit", None, 300, 300), (300, 200)),
    (("exact", None, 640, None, True), (640, 427)),
    (("exact", None, 640, 640, False), (640, 640)),
    (("crop", None, 500, 500), (500, 500)),
])
def test_target_size(args, expected):
    mode, percent, *rest = args
    kw = {"percent": percent or 50}
    if rest:
        kw["width"] = rest[0]
    if len(rest) > 1:
        kw["height"] = rest[1]
    if len(rest) > 2:
        kw["keep_aspect"] = rest[2]
    assert images.target_size(1200, 800, mode, **kw) == expected


def test_resize_writes_files(pics, tmp_path):
    out, old, new = images.resize_image(str(pics[1]), "fit", width=800, height=800, out_dir=str(tmp_path / "r"))
    assert old == (1600, 1200) and new == (800, 600) and Path(out).name == "photo_resized.jpg"
    out2, _, new2 = images.resize_image(str(pics[0]), "crop", width=256, height=256, fmt="webp",
                                        out_dir=str(tmp_path / "r"))
    assert new2 == (256, 256) and out2.endswith(".webp")


def test_bad_image(tmp_path):
    bad = tmp_path / "x.png"
    bad.write_text("nope")
    with pytest.raises(ClipError):
        images.convert_image(str(bad), "jpg")


# ------------------------------------------------------------ compressor
def test_compress_image(pics, tmp_path):
    res = compress.compress_file(str(pics[1]), "balanced", str(tmp_path / "c"), FFMPEG, FFPROBE, threading.Event(),
                                 noop, noop)
    assert res.after < res.before and res.saved_pct > 20 and res.kind == "image"


def test_compress_pdf(tmp_path, pics):
    import pymupdf
    pdf = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, filename=str(pics[1]))
        page.insert_text((72, 72), "Hello compressor", fontsize=24)
    doc.save(pdf)
    res = compress.compress_file(str(pdf), "strong", str(tmp_path / "c"), FFMPEG, FFPROBE, threading.Event(),
                                 noop, noop)
    assert res.kind == "pdf" and res.after < res.before
    d2 = pymupdf.open(res.path)
    assert d2.page_count == 3 and "Hello compressor" in d2[0].get_text()


@needs_ff
def test_compress_video_and_audio(media, tmp_path):
    rv = compress.compress_file(str(media["video"]), "strong", str(tmp_path), FFMPEG, FFPROBE, threading.Event(),
                                noop, noop)
    assert rv.kind == "video" and rv.after < rv.before and probe(rv.path).height == 720
    ra = compress.compress_file(str(media["audio"]), "balanced", str(tmp_path), FFMPEG, FFPROBE, threading.Event(),
                                noop, noop)
    assert ra.kind == "audio" and ra.after < ra.before and ra.path.endswith(".m4a")


def test_compress_other_files_zip(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello world " * 5000)
    res = compress.compress_file(str(f), "strong", None, None, None, threading.Event(), noop, noop)
    assert res.kind == "zip" and res.path.endswith(".zip") and res.after < res.before / 10


def test_compress_keeps_original_when_no_gain(tmp_path):
    p = tmp_path / "tiny.png"
    Image.new("RGB", (8, 8), (0, 0, 0)).save(p, optimize=True)
    res = compress.compress_file(str(p), "light", str(tmp_path / "c"), None, None, threading.Event(), noop, noop)
    assert res.path == str(p) and "original kept" in res.note


# ------------------------------------------------------------ HEIC + WebP
@pytest.mark.skipif(not images.HEIF, reason="pillow-heif not installed")
def test_heic_in_and_out(pics, tmp_path):
    heic = images.convert_image(str(pics[1]), "heic", str(tmp_path / "h"), quality=70)
    assert heic.endswith(".heic") and Path(heic).stat().st_size < pics[1].stat().st_size
    with Image.open(heic) as im:
        assert im.size == (1600, 1200)
    # HEIC opens as an input for every image tool
    back = images.convert_image(heic, "jpg", str(tmp_path / "j"))
    assert back.endswith(".jpg")
    out, old, new = images.resize_image(heic, "percent", 25, out_dir=str(tmp_path / "r"))
    assert out.endswith(".heic") and new == (400, 300)  # "Same" keeps HEIC
    res = compress.compress_file(heic, "strong", str(tmp_path / "c"), None, None, threading.Event(), noop, noop)
    assert res.kind == "image" and res.path.endswith((".heic", Path(heic).name))


def test_heic_alpha_png(pics, tmp_path):
    if not images.HEIF:
        pytest.skip("pillow-heif not installed")
    out = images.convert_image(str(pics[0]), "heic", str(tmp_path))
    with Image.open(out) as im:
        assert im.size == (1200, 800)


def test_webp_everywhere(pics, tmp_path):
    w = images.convert_image(str(pics[1]), "webp", str(tmp_path / "w"), quality=75)
    out, _, new = images.resize_image(w, "fit", width=400, height=400, out_dir=str(tmp_path / "r"))
    assert out.endswith(".webp") and new == (400, 300)
    res = compress.compress_file(w, "strong", str(tmp_path / "c"), None, None, threading.Event(), noop, noop)
    assert res.kind == "image"
    assert ".webp" in images.IMAGE_IN and ".heic" in images.IMAGE_IN


@needs_ff
def test_probe_without_ffprobe_matches(media):
    """The installer ships only ffmpeg; probing falls back to parsing `ffmpeg -i`."""
    a = convert.probe(str(media["video"]), FFPROBE)
    b = convert.probe(str(media["video"]), None, FFMPEG)
    assert (b.has_video, b.has_audio, b.width, b.height, b.vcodec) == (a.has_video, a.has_audio, a.width, a.height,
                                                                         a.vcodec)
    assert b.duration == pytest.approx(a.duration, abs=0.05) and b.fps == pytest.approx(a.fps, abs=0.01)
    c = convert.probe(str(media["audio"]), None, FFMPEG)
    assert c.has_audio and not c.has_video and c.duration == pytest.approx(4.0, abs=0.05)


@needs_ff
def test_convert_and_compress_without_ffprobe(media, tmp_path):
    out = convert.convert_file(str(media["video"]), "mp3", str(tmp_path), FFMPEG, None, threading.Event(), noop, noop)
    assert Path(out).exists()
    r = compress.compress_file(str(media["video"]), "strong", str(tmp_path / "c"), FFMPEG, None, threading.Event(),
                               noop, noop)
    assert Path(r.path).exists()
