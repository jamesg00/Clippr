"""Offscreen smoke run of the tool windows with real sample files; saves screenshots.

Usage: QT_QPA_PLATFORM=offscreen python tests/tools_smoke.py <outdir>
"""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "tool_shots")
out.mkdir(parents=True, exist_ok=True)
work = out / "work"
work.mkdir(exist_ok=True)
ff = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
vid = work / "Holiday clip.mp4"
if not vid.exists():
    subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=6", "-f", "lavfi", "-i",
                         "sine=frequency=440:duration=6", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14",
                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-shortest", str(vid)], check=True)
wav = work / "Voice memo.wav"
if not wav.exists():
    subprocess.run(ff + ["-f", "lavfi", "-i", "sine=frequency=300:duration=5", str(wav)], check=True)
photos = []
for i, (w, h) in enumerate([(4032, 3024), (3000, 2000), (1200, 1600)]):
    p = work / f"IMG_10{i}{i}.jpg"
    if not p.exists():
        Image.effect_noise((w // 4, h // 4), 70).resize((w, h)).convert("RGB").save(p, quality=97)
    photos.append(p)
png = work / "logo.png"
if not png.exists():
    im = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((100, 100, 924, 924), fill=(46, 229, 157, 255))
    im.save(png)
pdf = work / "Scanned contract.pdf"
if not pdf.exists():
    import pymupdf
    d = pymupdf.open()
    for _ in range(4):
        pg = d.new_page()
        pg.insert_image(pg.rect, filename=str(photos[0]))
        pg.insert_text((72, 72), "Contract page", fontsize=20)
    d.save(pdf)
notes = work / "notes.txt"
notes.write_text("meeting notes " * 4000)

app = QApplication(sys.argv)
from clipdl.core import audio_dl, settings  # noqa: E402
from clipdl.ui import theme  # noqa: E402

theme.load_fonts()
from clipdl.app import AppContext  # noqa: E402
from clipdl.controller import AppController  # noqa: E402
from clipdl.ui.main_window import MainWindow  # noqa: E402
from clipdl.ui.tools.tools import AudioTool  # noqa: E402

cfg = settings.AppSettings(save_folder=str(work / "out"), appearance="solid")
ctx = AppContext(cfg, work / "settings.json")
win = MainWindow()
ctx.main = win
ctl = AppController(win, cfg, settings_path=work / "settings.json")
ctx.appearance.register(win)
win.sessionRequested.connect(ctx.switch_session)
win.resize(1280, 820)
win.show()


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.01)


def shot(w, name):
    pump(0.3)
    w.grab().save(str(out / f"{name}.png"))
    print("shot", name)


def run_tool(w, timeout=120):
    w.start()
    t0 = time.time()
    while w.running and time.time() - t0 < timeout:
        pump(0.1)
    pump(0.3)
    res = {it["row"].name._full: (it["status"], it["row"].sub._full) for it in w.items.values()}
    for k, v in res.items():
        print("   ", k, "->", v)
    assert all(s == "done" for s, _ in res.values()), res
    return res


shot(win, "00_main_with_tools")
win.switcher._open()
pump(0.4)
win.switcher.menu.grab().save(str(out / "00b_session_menu.png"))
print("shot 00b_session_menu")
win.switcher.menu.close()

# --- audio: use the local file through yt-dlp's generic extractor instead of a real link
orig_task = AudioTool.task


def local_task(self, item, o):
    def fn(progress, log, cancel):
        return audio_dl.download_audio(item["src"], o["format"], o["bitrate"], o["folder"], self.ctx.ffmpeg, cancel,
                                       progress, log, cover=False, metadata=o["tags"], allow_files=True)
    return fn


AudioTool.task = local_task
ctx.switch_session("audio")
a = ctx.tools["audio"]
shot(win, "01_audio_empty")
a._add_item(vid.resolve().as_uri(), "youtube.com/watch?v=dQw4w9WgXcQ", "YouTube · waiting")
a._add_item(vid.resolve().as_uri(), "instagram.com/reel/C9abcDEF123/", "Instagram · waiting")
a._add_item(vid.resolve().as_uri(), "x.com/NASA/status/1834567890123456789", "X · waiting")
a.save_to.edit.setText(str(work / "audio"))
shot(win, "02_audio_queue")
run_tool(a)
shot(win, "03_audio_done")
AudioTool.task = orig_task

# --- convert
ctx.switch_session("convert")
c = ctx.tools["convert"]
c.add_files([str(vid), str(wav)])
c.fmt.set_value("mp3")
c._sync()
c.save_to.toggle.setChecked(False)
c.save_to.edit.setText(str(work / "converted"))
c.start()
pump(0.25)
shot(win, "04_convert_running")
t0 = time.time()
while c.running and time.time() - t0 < 120:
    pump(0.1)
pump(0.3)
shot(win, "05_convert_done")
assert all(it["status"] == "done" for it in c.items.values()), [(it["row"].sub._full) for it in c.items.values()]

# --- pictures go through the same Convert session
ctx.switch_session("convert")
im = ctx.tools["convert"]
im.clear_finished()
im.add_files([str(p) for p in photos] + [str(png)])
im.img_fmt.set_value("webp")
im._sync()
im.save_to.toggle.setChecked(False)
im.save_to.edit.setText(str(work / "webp"))
run_tool(im)
shot(win, "06_images_done")

# --- resize
ctx.switch_session("resize")
r = ctx.tools["resize"]
r.add_files([str(p) for p in photos])
r.mode.set_value("fit")
r.w.setValue(1920)
r.h.setValue(1080)
r._sync()
r.save_to.toggle.setChecked(False)
r.save_to.edit.setText(str(work / "resized"))
shot(win, "07_resize_ready")
run_tool(r)
shot(win, "08_resize_done")

# --- compress
ctx.switch_session("compress")
k = ctx.tools["compress"]
shot(win, "09_compress_empty")
k.add_files([str(pdf), str(photos[0]), str(vid), str(notes)])
k.save_to.toggle.setChecked(False)
k.save_to.edit.setText(str(work / "compressed"))
run_tool(k)
shot(win, "10_compress_done")

# --- settings popover
ctx.appearance.show_popover(win)
pump(0.4)
pops = [w for w in app.topLevelWidgets() if w.objectName() == "Popover" and w.isVisible()]
if pops:
    pops[0].grab().save(str(out / "11_settings_popover.png"))
    print("shot 11_settings_popover")
    pops[0].close()


# --- simulated see-through modes over a "desktop" (offscreen can't do real DWM effects)
def desktop(W, H):
    wall = Image.new("RGB", (W, H), (18, 24, 38))
    d = ImageDraw.Draw(wall)
    for (x, y, rr, col) in [(0.2, 0.3, 0.35, (40, 120, 200)), (0.8, 0.75, 0.4, (200, 90, 60)),
                            (0.6, 0.15, 0.25, (60, 180, 120))]:
        d.ellipse([W * x - W * rr, H * y - W * rr, W * x + W * rr, H * y + W * rr], fill=col)
    wall = wall.filter(ImageFilter.GaussianBlur(120))
    d = ImageDraw.Draw(wall)
    try:
        f = ImageFont.truetype(str(Path(theme.__file__).resolve().parents[2] / "assets/fonts/Inter-SemiBold.ttf"), 42)
    except OSError:
        f = None
    for i in range(14):  # pretend desktop: text + icons to prove it's really see-through
        d.text((60, 40 + i * 62), f"~/Projects/beats  $ ffmpeg -i track_{i:02d}.wav -b:a 320k out.mp3", fill=(235, 235, 235), font=f)
    for i in range(6):
        d.rounded_rectangle([W - 200, 60 + i * 130, W - 100, 160 + i * 130], 18, fill=(250, 200, 80))
    return wall


def see_through(w, mode, opacity, name):
    w.setAttribute(Qt.WA_TranslucentBackground, True)
    w.backdrop = mode
    w.opacity = opacity
    app.setStyleSheet(theme.qss(mode, opacity))
    pump(0.4)
    layer = w.grab().toImage()
    tmp = out / "_layer.png"
    layer.save(str(tmp))
    lay = Image.open(tmp).convert("RGBA")
    wall = desktop(lay.width, lay.height)
    if mode == "frosted":
        wall = wall.filter(ImageFilter.GaussianBlur(28))
    Image.alpha_composite(wall.convert("RGBA"), lay).convert("RGB").save(out / f"{name}.png")
    print("shot", name)


ctx.switch_session("clip")
see_through(win, "clear", 0.40, "12_main_clear")
ctx.switch_session("compress")
see_through(win, "clear", 0.40, "13_compress_clear")
ctx.switch_session("clip")
see_through(win, "frosted", 0.40, "14_main_frosted")
ctx.save()
print("settings tools keys:", sorted(settings.load(work / "settings.json").tools))
print("OK")
