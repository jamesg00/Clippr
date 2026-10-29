"""Offscreen UI smoke run: drives every state with a local sample video and saves screenshots.

Usage: QT_QPA_PLATFORM=offscreen python tests/ui_smoke.py <outdir>
"""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from clipdl.core import clipper, settings  # noqa: E402
from clipdl.core.media_info import Stream, VideoInfo  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "shots")
out.mkdir(parents=True, exist_ok=True)
work = out / "work"
work.mkdir(exist_ok=True)
sample = work / "sample.mp4"
if not sample.exists():
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=1280x720:rate=30:duration=60", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=60,volume=0.6", "-af", "volume='0.3+0.7*abs(sin(t*1.3))':eval=frame",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(sample)], check=True)

app = QApplication(sys.argv)
from clipdl.ui import theme  # noqa: E402
from clipdl.ui.main_window import MainWindow  # noqa: E402
from clipdl.controller import AppController, State  # noqa: E402

theme.load_fonts()
app.setStyleSheet(theme.qss(False))
cfg = settings.AppSettings(save_folder=str(work / "out"), glass=False)
win = MainWindow()
ctl = AppController(win, cfg, settings_path=work / "settings.json")
win.resize(1280, 820)
win.show()


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(QEventLoop.AllEvents, 50)
        time.sleep(0.01)


def shot(name):
    pump(0.25)
    win.grab().save(str(out / f"{name}.png"))
    print("shot", name)


# fake info backed by the local sample
local = Stream(url=sample.resolve().as_uri(), vcodec="avc1.64001f", acodec="mp4a.40.2", height=720, fps=30)
info = VideoInfo(id="sample", title="Sample video: synthetic test pattern with a long-ish title", channel="Test Channel",
                 duration=60.0, thumbnail=None, webpage_url="", heights=[360, 480, 720], max_height=720, fps=30.0,
                 preview_video=local, preview_audio=None,
                 waveform_audio=Stream(url=str(sample)))
# route downloads to the local file instead of YouTube
clipper.Clipper._resolve_streams = lambda self, req: (Stream(str(sample), vcodec="avc1.64001f", height=720, fps=30),
                                                       None)

shot("01_empty")
win.url_bar.set_text("https://www.vimeo.com/123")
ctl.load_url("https://www.vimeo.com/123")
shot("02_empty_invalid")

ctl.url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=12"
ctl.token += 1
ctl.set_state(State.LOADING)
win.url_bar.set_text(ctl.url)
shot("03_loading")
ctl._on_info((str(ctl.token), info))
pump(2.5)  # waveform job
win.player.seek_to(18.4)
shot("04_ready_file_tab")
win.export.set_tab("output")
win.export.fmt_seg._clicked("webm")
win.export.fmt_seg.set_value("webm")
win.export._on_format("webm")
win.export._set(resolution=480, fps=24)
shot("05_ready_output_tab")
win.export._on_format("gif")
shot("06_output_gif")
win.export._on_format("mp3")
shot("07_output_mp3")
win.export._set(format="mp4", resolution="src", fps="src", codec="h264", quality=70, audio=True, audio_bitrate=192)
win.export.set_tab("file")
ctl._set_start(14.0)
ctl._set_end(24.5)

ctl.download()
seen_mid = False
t0 = time.time()
while ctl.state == State.DOWNLOADING and time.time() - t0 < 60:
    pump(0.05)
    p = ctl._last_progress
    if not seen_mid and p is not None and 35 <= p.percent <= 80:
        shot("08_downloading")
        seen_mid = True
pump(0.3)
print("final state", ctl.state, ctl.last_result)
shot("09_done")
assert ctl.state == State.DONE, ctl.state
assert Path(ctl.last_result.path).is_file()

# error card
ctl._show_error("Couldn't make the clip", "YouTube refused the stream (403).",
                "[ffmpeg] Server returned 403 Forbidden (access denied)\nhttps://rr3---sn.googlevideo.com/…")
shot("10_error")

# cancel flow
ctl.set_state(State.READY)
win.export._set(codec="h265", quality=100)
ctl._set_start(0)
ctl._set_end(59)
ctl.download()
pump(1.2)
ctl.cancel()
t0 = time.time()
while ctl.state == State.DOWNLOADING and time.time() - t0 < 20:
    pump(0.05)
print("after cancel", ctl.state, list((work / "out").iterdir()))
assert ctl.state == State.READY
assert not list((work / "out").glob(".clipdl-tmp-*"))
shot("11_after_cancel")

ctl.save_settings()
print("settings", (work / "settings.json").read_text()[:200])


# ---- glass preview: render with the glass tint onto a blurred wallpaper (offscreen can't do real DWM blur)
from PySide6.QtCore import Qt as _Qt  # noqa: E402
ctl.set_state(State.DONE)
win.done.tick.play()
pump(1.2)
win.setAttribute(_Qt.WA_TranslucentBackground, True)
win.backdrop = "frosted"
win.opacity = 0.30
app.setStyleSheet(theme.qss("frosted"))
pump(0.4)
img = win.grab().toImage()
img.save(str(out / "_glass_layer.png"))
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
W, H = img.width(), img.height()
wall = Image.new("RGB", (W, H), (8, 12, 10))
d = ImageDraw.Draw(wall)
for (x, y, r, c) in [(0.2, 0.25, 0.45, (30, 150, 105)), (0.85, 0.8, 0.4, (20, 90, 130)), (0.7, 0.1, 0.3, (120, 160, 60)),
                     (0.35, 0.95, 0.3, (140, 60, 120))]:
    d.ellipse([W * x - W * r, H * y - W * r, W * x + W * r, H * y + W * r], fill=c)
wall = wall.filter(ImageFilter.GaussianBlur(160))
blurred = wall.filter(ImageFilter.GaussianBlur(40))  # what acrylic shows through the window
layer = Image.open(out / "_glass_layer.png").convert("RGBA")
comp = Image.alpha_composite(blurred.convert("RGBA"), layer)
comp.convert("RGB").save(out / "12_glass_preview.png")
print("shot 12_glass_preview")
print("OK")
