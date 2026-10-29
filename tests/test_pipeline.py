"""Integration tests: real ffmpeg encodes on generated sample media (no network)."""
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipdl.core import clipper, waveform
from clipdl.core.media_info import Stream
from clipdl.core.settings import OutputSettings

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg not installed")


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    muxed = d / "muxed.mp4"
    vonly = d / "video.mp4"
    aonly = d / "audio.m4a"
    base = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run(base + ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=20",
                           "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
                           "-c:v", "libx264", "-preset", "ultrafast", "-g", "60", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-shortest", str(muxed)], check=True)
    subprocess.run(base + ["-i", str(muxed), "-an", "-c", "copy", str(vonly)], check=True)
    subprocess.run(base + ["-i", str(muxed), "-vn", "-c", "copy", str(aonly)], check=True)
    return {"muxed": muxed, "video": vonly, "audio": aonly}


def probe(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,height,r_frame_rate:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    fps = None
    if v:
        n, dd = v["r_frame_rate"].split("/")
        fps = round(int(n) / int(dd), 2)
    return {"dur": float(j["format"]["duration"]), "v": v and v["codec_name"], "a": a and a["codec_name"],
            "h": v and v.get("height"), "fps": fps}


def run(media, tmp_path, split=True, cancel=None, start=4.0, end=7.5, precise=True, **out):
    if split:
        streams = (Stream(str(media["video"]), vcodec="avc1.64001f", height=720, fps=30),
                   Stream(str(media["audio"]), acodec="mp4a.40.2"))
    else:
        streams = (Stream(str(media["muxed"]), vcodec="avc1.64001f", acodec="mp4a.40.2", height=720, fps=30), None)
    req = clipper.ClipRequest(url="local", start=start, end=end, output=OutputSettings(**out), precise=precise,
                              folder=str(tmp_path), filename="My clip", ffmpeg=FFMPEG, src_height=720, src_fps=30)
    events, logs = [], []
    c = clipper.Clipper(req, cancel or threading.Event(), events.append, logs.append,
                        resolve_streams=lambda r: streams)
    return c.run(), events, logs


@pytest.mark.parametrize("split", [True, False])
@pytest.mark.parametrize("out,expect", [
    ({}, {"v": "h264", "a": "aac", "h": 720}),
    ({"resolution": 480, "fps": 24}, {"v": "h264", "a": "aac", "h": 480, "fps": 24}),
    ({"codec": "h265"}, {"v": "hevc", "a": "aac"}),
    ({"format": "webm"}, {"v": "vp9", "a": "opus"}),
    ({"format": "mov"}, {"v": "h264", "a": "aac"}),
    ({"format": "gif", "resolution": 360, "fps": 15}, {"v": "gif", "a": None, "h": 360, "fps": 15}),
    ({"format": "mp3"}, {"v": None, "a": "mp3"}),
    ({"audio": False}, {"v": "h264", "a": None}),
])
def test_formats(media, tmp_path, split, out, expect):
    res, events, logs = run(media, tmp_path, split=split, **out)
    p = probe(res.path)
    for k, v in expect.items():
        assert p[k] == v, (k, p)
    assert abs(p["dur"] - 3.5) < 0.2, p
    assert Path(res.path).name.startswith("My clip.")
    assert not list(tmp_path.glob(".clipdl-tmp-*")), "temp folder left behind"
    pcts = [e.percent for e in events]
    assert pcts == sorted(pcts), "progress went backwards"
    assert events[-1].phase == "finishing" and events[-1].percent == 100


def test_stream_copy_fast_mode(media, tmp_path):
    res, events, logs = run(media, tmp_path, precise=False)
    assert res.stream_copy
    p = probe(res.path)
    assert p["v"] == "h264" and p["a"] == "aac"
    # keyframe-aligned: may start up to one GOP (2 s) early, never shorter
    assert 3.3 < p["dur"] < 5.8


def test_unique_names(media, tmp_path):
    r1, *_ = run(media, tmp_path)
    r2, *_ = run(media, tmp_path)
    assert Path(r1.path).name == "My clip.mp4" and Path(r2.path).name == "My clip (2).mp4"


def test_cancel_cleans_up(media, tmp_path):
    cancel = threading.Event()
    result = {}

    def go():
        try:
            run(media, tmp_path, cancel=cancel, start=0, end=19.9, codec="h265", quality=100)
            result["r"] = "finished"
        except clipper.Cancelled:
            result["r"] = "cancelled"

    t = threading.Thread(target=go)
    t.start()
    time.sleep(0.6)
    cancel.set()
    t.join(20)
    assert result.get("r") == "cancelled"
    assert not list(tmp_path.iterdir()), "files left after cancel"


def test_bad_input_is_friendly_error(media, tmp_path):
    req = clipper.ClipRequest(url="x", start=1, end=2, output=OutputSettings(), precise=True,
                              folder=str(tmp_path), filename="c", ffmpeg=FFMPEG)
    c = clipper.Clipper(req, threading.Event(), lambda p: None, lambda s: None,
                        resolve_streams=lambda r: (Stream(str(tmp_path / "nope.mp4"), vcodec="avc1"), None))
    # direct path fails -> fallback tries yt-dlp on a bogus URL -> friendly ClipError
    with pytest.raises(clipper.ClipError):
        c.run()
    assert not list(tmp_path.glob(".clipdl-tmp-*"))


def test_redact():
    out = clipper._redact(["-headers", "Cookie: secret\r\n", "-i", "https://rr1.googlevideo.com/videoplayback?sig=abc"])
    assert "secret" not in " ".join(out) and "sig=abc" not in " ".join(out)


def test_progress_parse():
    d = clipper.parse_progress_block(["out_time_us=1500000", "total_size=1024", "speed=2.5x", "progress=continue"])
    assert clipper._out_seconds(d) == 1.5
    assert clipper._out_seconds({"out_time_us": "N/A", "out_time": "00:00:02.500000"}) == 2.5


def test_waveform(media):
    peaks = waveform.compute_peaks(FFMPEG, Stream(str(media["audio"])), 20, threading.Event(), buckets=100)
    assert len(peaks) == 100 and max(peaks) <= 1 and min(peaks) >= 0 and max(peaks) > 0.5
    assert waveform.peaks_from_pcm(b"", 10) == [0.0] * 10
