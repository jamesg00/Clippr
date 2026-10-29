"""Free-transform editor, paste / drop from the web, drop overlay (offscreen)."""
import base64
import http.server
import io
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipdl.core import images, settings, webimage  # noqa: E402
from clipdl.core.images import Transform  # noqa: E402


# ---------------------------------------------------------------- core: transform rendering
@pytest.fixture
def pic(tmp_path):
    im = Image.new("RGB", (400, 200), (255, 0, 0))
    im.paste((0, 0, 255), (200, 0, 400, 200))  # left red, right blue
    p = tmp_path / "pic.png"
    im.save(p)
    return p


def test_identity_transform_is_lossless(pic):
    im = Image.open(pic)
    t = images.initial_transform(400, 200)
    assert (t.canvas_w, t.canvas_h, t.sx) == (400, 200, 1.0) and (t.cx, t.cy) == (200, 100)
    out = images.render_transform(im, t)
    assert out.size == (400, 200)
    assert out.getpixel((10, 10))[:3] == (255, 0, 0) and out.getpixel((390, 10))[:3] == (0, 0, 255)


def test_flip_rotate_and_canvas(pic):
    im = Image.open(pic)
    t = replace(images.initial_transform(400, 200), flip_h=True)
    out = images.render_transform(im, t)
    assert out.getpixel((10, 10))[:3] == (0, 0, 255)
    t = Transform(200, 400, 100, 200, 1, 1, rot=90)  # quarter turn clockwise: red ends up on top
    out = images.render_transform(im, t)
    assert out.size == (200, 400)
    assert out.getpixel((100, 10))[:3] == (255, 0, 0) and out.getpixel((100, 390))[:3] == (0, 0, 255)
    # extended canvas: empty area is transparent, or the fill colour
    t = Transform(600, 200, 300, 100)
    out = images.render_transform(im, t)
    assert out.getpixel((20, 100))[3] == 0 and out.getpixel((300, 100))[3] == 255
    out = images.render_transform(im, replace(t, bg="#ffffff"))
    assert out.getpixel((20, 100)) == (255, 255, 255, 255)


def test_crop_and_fit_helpers():
    t = images.initial_transform(400, 200, "crop", width=100, height=100)
    assert (t.canvas_w, t.canvas_h) == (100, 100) and t.sx == pytest.approx(0.5)
    t = images.fit_transform(Transform(300, 300, 0, 0, 5, 5, rot=90), 400, 200)
    assert t.sx == pytest.approx(0.75) and (t.cx, t.cy) == (150, 150)
    t = images.fit_transform(Transform(300, 300, 0, 0), 400, 200, cover=True)
    assert t.sx == pytest.approx(1.5)


def test_edit_image_writes_file(pic, tmp_path):
    t = Transform(300, 300, 150, 150, 0.5, 0.5, rot=30, bg="#000000")
    path, old, new = images.edit_image(str(pic), t, "jpg", out_dir=str(tmp_path / "o"))
    assert Path(path).exists() and old == (400, 200) and new == (300, 300)
    assert Path(path).name == "pic_edited.jpg"


def test_exact_with_lock_keeps_proportions():
    assert images.target_size(400, 200, "exact", width=100, height=999, keep_aspect=True) == (100, 50)
    assert images.target_size(400, 200, "exact", width=100, height=999, keep_aspect=False) == (100, 999)


# ---------------------------------------------------------------- core: web pictures
def test_img_sources_from_html():
    html = ('<div><img alt="x" srcset="/a-320.jpg 320w, /a-1280.jpg 1280w" src="/a.jpg">'
            '<img src="https://cdn.example.com/b.png?x=1&amp;y=2"></div>')
    srcs = webimage.img_sources(html, "https://example.com/page")
    assert srcs[0] == "https://example.com/a-1280.jpg"
    assert "https://example.com/a.jpg" in srcs and "https://cdn.example.com/b.png?x=1&y=2" in srcs


def test_data_uri(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    p = webimage.download_image(uri, tmp_path)
    assert Path(p).suffix == ".png" and Image.open(p).size == (8, 8)


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    Image.new("RGB", (40, 30), (9, 9, 9)).save(root / "photo.webp", "WEBP")
    (root / "page.html").write_text("<html>not a picture</html>")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_download_image(server, tmp_path):
    p = webimage.download_image(server + "/photo.webp", tmp_path)
    assert Path(p).name == "photo.webp" and Image.open(p).size == (40, 30)
    from clipdl.core.clipper import ClipError
    with pytest.raises(ClipError):
        webimage.download_image(server + "/page.html", tmp_path)


# ---------------------------------------------------------------- UI
@pytest.fixture
def ctx(qtbot, tmp_path, monkeypatch):
    from clipdl.app import AppContext
    from clipdl.controller import AppController
    from clipdl.core import paths
    from clipdl.ui import theme
    from clipdl.ui.main_window import MainWindow
    monkeypatch.setattr(paths, "default_download_dir", lambda: tmp_path / "dl")
    theme.load_fonts()
    cfg = settings.AppSettings(save_folder=str(tmp_path), appearance="solid")
    c = AppContext(cfg, tmp_path / "s.json")
    win = MainWindow()
    qtbot.addWidget(win)
    c.main = win
    c.ctl = AppController(win, cfg, settings_path=tmp_path / "s.json")
    win.sessionRequested.connect(c.switch_session)
    win.resize(1280, 860)
    win.show()
    return c


def test_resize_editor_gestures(ctx, qtbot, pic):
    from PySide6.QtCore import QPointF, Qt
    ctx.switch_session("resize")
    r = ctx.tools["resize"]
    r.mode.set_value("exact")
    r._sync()
    r.add_files([str(pic)])
    it = next(iter(r.items.values()))
    assert r.sel == it["id"] and r.editor.t is not None and it["edit"] is None
    cv = r.editor.canvas
    cv.resize(800, 500)
    cv.fit_view()
    t0 = cv.t.copy()
    # drag the right-middle handle outwards with the chain locked -> proportional scale
    h = next(p for hx, hy, p in cv._layer_handles() if (hx, hy) == (1, 0))
    qtbot.mousePress(cv, Qt.LeftButton, pos=h.toPoint())
    qtbot.mouseMove(cv, pos=(h + QPointF(80, 0)).toPoint())
    qtbot.mouseRelease(cv, Qt.LeftButton, pos=(h + QPointF(80, 0)).toPoint())
    assert cv.t.sx > t0.sx and cv.t.sx == pytest.approx(cv.t.sy)
    assert it["edit"] is not None and "Custom" in it["row"].sub._full
    # canvas tab: extend the canvas to the right, the picture stays where it is on screen
    t1 = cv.t.copy()
    tab = next(p for ax, ay, p in cv._canvas_tabs() if (ax, ay) == (1, 0))
    cv.lock = False
    qtbot.mousePress(cv, Qt.LeftButton, pos=tab.toPoint())
    qtbot.mouseMove(cv, pos=(tab + QPointF(60, 0)).toPoint())
    qtbot.mouseRelease(cv, Qt.LeftButton, pos=(tab + QPointF(60, 0)).toPoint())
    assert cv.t.canvas_w > t1.canvas_w and cv.t.canvas_h == t1.canvas_h and cv.t.cx == pytest.approx(t1.cx)
    # undo goes back, reset returns to the batch settings
    r.editor.undo()
    assert r.editor.t.canvas_w == t1.canvas_w
    r.editor._action("reset")
    assert it["edit"] is None
    # W with the chain locked resizes both sides
    r.editor.chain.setChecked(True)
    w0, h0 = r.editor.t.canvas_w, r.editor.t.canvas_h
    r.editor.w_spin.setValue(w0 // 2)
    assert r.editor.t.canvas_h == round(h0 / 2)


def test_batch_chain_links_sides(ctx, pic):
    ctx.switch_session("resize")
    r = ctx.tools["resize"]
    r.add_files([str(pic)])
    r.mode.set_value("exact")
    r.aspect.setChecked(True)
    r.w.setValue(1000)
    assert r.h.value() == 500  # the picture is 2:1
    r.aspect.setChecked(False)
    r.w.setValue(300)
    assert r.h.value() == 500


def test_paste_image_and_files(ctx, qtbot, pic, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QColor, QGuiApplication, QImage
    ctx.switch_session("convert")
    page = ctx.tools["convert"]
    img = QImage(64, 48, QImage.Format_ARGB32)
    img.fill(QColor("#22cc88"))
    QGuiApplication.clipboard().setImage(img)
    ctx.ctl._on_paste_key()  # Ctrl+V is routed to the visible session
    assert len(page.items) == 1
    src = next(iter(page.items.values()))["src"]
    assert Path(src).parent.name == "Pasted images" and Image.open(src).size == (64, 48)
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(pic))])
    assert page.ingest_mime(md)
    assert len(page.items) == 2
    ok, title, *_ = page.describe_mime(md)
    assert ok and title == "Drop 1 file"
    bad = QMimeData()
    bad.setUrls([QUrl.fromLocalFile(str(tmp_path / "s.json"))])
    assert page.describe_mime(bad)[0] is False


def test_paste_web_link_downloads(ctx, qtbot, server):
    from PySide6.QtCore import QMimeData
    ctx.switch_session("resize")
    page = ctx.tools["resize"]
    md = QMimeData()
    md.setHtml(f'<img src="{server}/photo.webp">')
    assert page.ingest_mime(md)
    qtbot.waitUntil(lambda: len(page.items) == 1, timeout=10000)
    assert next(iter(page.items.values()))["src"].endswith("photo.webp")


def test_drop_overlay_animates(ctx, qtbot):
    from PySide6.QtCore import QPointF
    ctx.switch_session("compress")
    fx = ctx.tools["compress"].fx
    fx.enter(QPointF(100, 100), True, "Drop 2 files")
    qtbot.wait(80)
    assert fx.isVisible() and fx._fade > 0
    fx.drop(QPointF(120, 110))
    assert fx._burst
    qtbot.waitUntil(lambda: not fx.isVisible(), timeout=3000)


def test_link_drop_on_clip_page(ctx):
    from PySide6.QtCore import QMimeData
    md = QMimeData()
    md.setText("look https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert ctx.main._link_in(md) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    md.setText("nothing here")
    assert ctx.main._link_in(md) is None


def test_audio_track_picker(ctx):
    from clipdl.core.media_info import VideoInfo
    e = ctx.main.export
    e.set_audio_tracks([("en", "English", True), ("pt-BR", "Portuguese (Brazil)", False)], "en")
    assert e.track_box.count() == 2 and e.audio_lang() == "en"
    seen = []
    e.audioTrackChanged.connect(seen.append)
    e.track_box.setCurrentIndex(1)
    assert seen == ["pt-BR"]
    e.set_audio_tracks([], None)
    assert e.g_track.isHidden()
    assert VideoInfo.__dataclass_fields__["audio_lang"]


def test_convert_handles_media_and_pictures(ctx, qtbot, pic, tmp_path):
    import shutil
    import subprocess
    ff = shutil.which("ffmpeg")
    if not ff:
        pytest.skip("ffmpeg missing")
    wav = tmp_path / "tone.wav"
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=duration=1", str(wav)],
                   check=True)
    ctx.switch_session("convert")
    c = ctx.tools["convert"]
    c.add_files([str(pic), str(wav)])
    kinds = sorted(it["kind"] for it in c.items.values())
    assert kinds == ["image", "media"]
    assert "1 in the list" in c.img_head.count.text() and "1 in the list" in c.media_head.count.text()
    c.fmt.set_value("mp3")
    c.img_fmt.set_value("webp")
    c._sync()
    c.save_to.toggle.setChecked(False)
    c.save_to.edit.setText(str(tmp_path / "out"))
    c.start()
    qtbot.waitUntil(lambda: not c.running, timeout=60000)
    outs = sorted(p.suffix for p in (tmp_path / "out").iterdir())
    assert outs == [".mp3", ".webp"]
