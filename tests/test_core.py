import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipdl.core import encode, media_info, settings
from clipdl.core.settings import OutputSettings
from clipdl.core.timefmt import fmt_time, parse_time


# ------------------------------------------------------------ time

@pytest.mark.parametrize("text,sec", [
    ("90", 90), ("1:30", 90), ("01:01:30", 3690), ("1:30.5", 90.5), (" 0:05 ", 5), ("0", 0), ("12.25", 12.25),
])
def test_parse_time_ok(text, sec):
    assert parse_time(text) == pytest.approx(sec)


@pytest.mark.parametrize("text", ["", "  ", "a", "1:2:3:4", "1::2", "-5", "1:75", "1:-2", ":30"])
def test_parse_time_bad(text):
    with pytest.raises(ValueError):
        parse_time(text)


@pytest.mark.parametrize("sec,out", [(0, "0:00"), (5, "0:05"), (90, "1:30"), (3690, "1:01:30"), (-3, "0:00")])
def test_fmt_time(sec, out):
    assert fmt_time(sec) == out


def test_fmt_time_tenths():
    assert fmt_time(90.5, tenths=True) == "1:30.5"
    assert fmt_time(90.0, tenths=True) == "1:30"
    assert fmt_time(59.96, tenths=True) == "1:00"


# ------------------------------------------------------------ settings

def test_settings_roundtrip(tmp_path):
    s = settings.AppSettings(save_folder="D:/clips", precise=False, appearance="clear", opacity=0.6,
                             cookies="firefox", tools={"audio": {"format": "mp3"}}, volume=0.3, loop=False,
                             output=OutputSettings(format="webm", resolution=720, fps=30, codec="vp9",
                                                   quality=55, audio=False, audio_bitrate=320),
                             window=[10, 20, 1280, 820])
    p = tmp_path / "s.json"
    settings.save(s, p)
    assert settings.load(p) == s


def test_settings_bad_file_falls_back(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    assert settings.load(p) == settings.AppSettings()
    assert settings.load(tmp_path / "missing.json") == settings.AppSettings()


def test_settings_coerces_bad_values(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"output": {"format": "avi", "resolution": 999, "fps": 7, "quality": 300,
                                       "audio_bitrate": 64, "codec": "xvid"},
                             "volume": 5, "glass": "yes", "window": [1, 2]}))
    s = settings.load(p)
    assert s.output == OutputSettings(quality=100)
    assert s.volume == 1.0 and s.glass is None and s.window is None


# ------------------------------------------------------------ encode rules

def test_normalize_rules():
    assert encode.normalize(OutputSettings(format="webm", codec="h264")).codec == "vp9"
    assert encode.normalize(OutputSettings(format="mov", codec="vp9")).codec == "h264"
    assert encode.normalize(OutputSettings(format="gif", audio=True)).audio is False


def test_crf_mapping():
    assert encode.crf_for("h264", 100) == 18
    assert encode.crf_for("h264", 70) == 23
    assert encode.crf_for("h264", 10) == 34
    assert encode.crf_for("h265", 70) == 27
    assert encode.crf_for("vp9", 100) == 20
    assert encode.crf_for("vp9", 10) == 45


def test_stream_copy_decision():
    d = OutputSettings()
    assert encode.needs_reencode(d, precise=True)
    assert not encode.needs_reencode(d, precise=False, src_vcodec="avc1.640028", src_height=1080, src_fps=30)
    assert encode.needs_reencode(d, precise=False, src_vcodec="vp09.00.40.08")
    assert encode.needs_reencode(OutputSettings(resolution=720), precise=False, src_vcodec="avc1", src_height=1080)
    # asking for the source height (or above) is not a change
    assert not encode.needs_reencode(OutputSettings(resolution=1080), precise=False, src_vcodec="avc1", src_height=1080)
    assert encode.needs_reencode(OutputSettings(fps=24), precise=False, src_vcodec="avc1", src_fps=30)
    assert not encode.needs_reencode(OutputSettings(fps=30), precise=False, src_vcodec="avc1", src_fps=30)
    for fmt in ("webm", "mov", "gif", "mp3"):
        assert encode.needs_reencode(OutputSettings(format=fmt), precise=False, src_vcodec="avc1")


def _args(**kw):
    return encode.build_encode_args(OutputSettings(**kw), src_height=1080, src_fps=30)


def test_args_mp4_h264_default():
    a = _args()
    assert a[a.index("-c:v") + 1] == "libx264"
    assert a[a.index("-crf") + 1] == "23"
    assert a[a.index("-c:a") + 1] == "aac" and a[a.index("-b:a") + 1] == "192k"
    assert "+faststart" in a and "-vf" not in a


def test_args_scale_and_fps():
    a = _args(resolution=720, fps=24)
    assert a[a.index("-vf") + 1] == "fps=24,scale=-2:720"


def test_args_h265_vp9_webm_mov():
    a = _args(codec="h265")
    assert "libx265" in a and "hvc1" in a and a[a.index("-crf") + 1] == "27"
    w = _args(format="webm", codec="h264")
    assert "libvpx-vp9" in w and "libopus" in w and "+faststart" not in w
    m = _args(format="mov", codec="vp9")
    assert "libx264" in m and "+faststart" in m


def test_args_audio_off():
    a = _args(audio=False)
    assert "-an" in a and "-c:a" not in a


def test_args_gif():
    a = _args(format="gif", resolution=480, fps=15, quality=100)
    graph = a[a.index("-filter_complex") + 1]
    assert graph.startswith("[0:v]fps=15,scale=-2:480:flags=lanczos,split[a][b];")
    assert graph.endswith("[vout]") and a[a.index("-map") + 1] == "[vout]"
    assert "max_colors=256" in graph and "-an" in a and "-loop" in a
    g2 = _args(format="gif")  # source size & fps
    assert g2[g2.index("-filter_complex") + 1].startswith("[0:v]split[a][b];")


def test_args_mp3():
    assert _args(format="mp3", audio_bitrate=320) == ["-vn", "-c:a", "libmp3lame", "-b:a", "320k"]


@pytest.mark.parametrize("fmt", settings.FORMATS)
@pytest.mark.parametrize("codec", settings.CODECS)
@pytest.mark.parametrize("res", settings.RESOLUTIONS)
@pytest.mark.parametrize("fps", settings.FRAME_RATES)
@pytest.mark.parametrize("audio", [True, False])
def test_args_every_combination_is_well_formed(fmt, codec, res, fps, audio):
    o = OutputSettings(format=fmt, codec=codec, resolution=res, fps=fps, audio=audio)
    a = encode.build_encode_args(o, src_height=1080, src_fps=30)
    assert all(isinstance(x, str) and x for x in a)
    # every flag that takes a value has one
    for flag in ("-c:v", "-c:a", "-b:a", "-crf", "-vf", "-filter_complex"):
        if flag in a:
            assert a.index(flag) + 1 < len(a) and not a[a.index(flag) + 1].startswith("-c")
    n = encode.normalize(o)
    assert ("-an" in a) == (not encode.has_audio(n))
    assert encode.ytdlp_format(o, precise=True)


def test_ytdlp_format():
    assert encode.ytdlp_format(OutputSettings(format="mp3"), True) == "ba/b"
    assert encode.ytdlp_format(OutputSettings(), False).startswith("bv*[vcodec^=avc1]")
    assert encode.ytdlp_format(OutputSettings(resolution=720), True) == "bv*[height<=720]+ba/b[height<=720]/b"
    assert encode.ytdlp_format(OutputSettings(format="gif"), True) == "bv*/b/b"


def test_estimates_are_sane():
    base = encode.estimate_size_mb(OutputSettings(), 36)
    assert 20 < base < 70
    assert encode.estimate_size_mb(OutputSettings(codec="h265"), 36) < base
    assert encode.estimate_size_mb(OutputSettings(resolution=480), 36) < base
    assert encode.estimate_size_mb(OutputSettings(format="mp3", audio_bitrate=192), 60) == pytest.approx(1.44)
    assert encode.estimate_size_mb(OutputSettings(), 10, src_tbr_kbps=4000, stream_copy=True) == pytest.approx(5.0)


def test_summary_parts():
    assert encode.summary_parts(OutputSettings(), 1080, 30) == ["MP4", "1080p", "30 fps", "H.264", "Audio 192k"]
    assert encode.summary_parts(OutputSettings(format="mp3"), 1080, 30) == ["MP3", "192 kbps"]
    assert encode.summary_parts(OutputSettings(format="gif", resolution=480, fps=15), 1080, 30) == \
        ["GIF", "480p", "15 fps", "No audio"]


def test_sanitize_and_unique(tmp_path):
    assert encode.sanitize_filename('My: "Video" / part?*') == "My Video part"
    assert encode.sanitize_filename("   ") == "clip"
    assert encode.sanitize_filename("CON") == "clip"
    assert encode.sanitize_filename("a" * 300) == "a" * 120
    p1 = encode.unique_path(tmp_path, "clip", "mp4")
    assert p1.name == "clip.mp4"
    p1.write_text("x")
    assert encode.unique_path(tmp_path, "clip", "mp4").name == "clip (2).mp4"


# ------------------------------------------------------------ media info

@pytest.mark.parametrize("url,expected,had_list", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),
    ("youtu.be/dQw4w9WgXcQ?t=42", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42", False),
    ("https://youtube.com/shorts/dQw4w9WgXcQ?feature=share", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=2", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", True),
    ("https://www.youtube.com/playlist?list=PL123", None, True),
    ("https://vimeo.com/123", None, False),
    ("https://www.instagram.com/reel/C9abcDEF123/?igsh=xyz", "https://www.instagram.com/reel/C9abcDEF123/", False),
    ("instagram.com/someone/reels/C9abcDEF123", "https://www.instagram.com/reel/C9abcDEF123/", False),
    ("https://www.instagram.com/p/C9abcDEF123/", "https://www.instagram.com/p/C9abcDEF123/", False),
    ("https://www.instagram.com/someuser/", None, False),
    ("https://twitter.com/NASA/status/1834567890123456789?s=20", "https://x.com/NASA/status/1834567890123456789", False),
    ("x.com/i/web/status/1834567890123456789", "https://x.com/i/status/1834567890123456789", False),
    ("https://x.com/home", None, False),
    ("not a url", None, False),
    ("https://www.youtube.com/watch?v=short", None, False),
])
def test_clean_url(url, expected, had_list):
    assert media_info.clean_url(url) == (expected, had_list)


def _fmt(fid, v=None, a=None, h=None, ext="mp4", tbr=1000, abr=None, fps=30):
    return {"format_id": fid, "url": f"https://x/{fid}", "protocol": "https", "vcodec": v or "none",
            "acodec": a or "none", "height": h, "ext": ext, "tbr": tbr, "abr": abr, "fps": fps if v else None}


FORMATS = [
    _fmt("139", a="mp4a.40.5", ext="m4a", tbr=48, abr=48),
    _fmt("140", a="mp4a.40.2", ext="m4a", tbr=128, abr=128),
    _fmt("251", a="opus", ext="webm", tbr=160, abr=160),
    _fmt("18", v="avc1.42001E", a="mp4a.40.2", h=360, tbr=500),
    _fmt("136", v="avc1.4d401f", h=720, tbr=2500),
    _fmt("137", v="avc1.640028", h=1080, tbr=4500),
    _fmt("248", v="vp9", h=1080, ext="webm", tbr=3000, fps=60),
]


def test_parse_info_and_preview():
    info = media_info.parse_info({"id": "abc", "title": "T", "uploader": "U", "duration": 768,
                                  "formats": FORMATS, "webpage_url": "w"})
    assert info.heights == [360, 720, 1080] and info.max_height == 1080 and info.fps == 60
    assert info.preview_video.url.endswith("/18") and info.preview_audio is None
    assert info.waveform_audio.url.endswith("/139")
    assert info.channel == "U"


def test_preview_split_when_no_muxed():
    v, a = media_info.pick_preview([f for f in FORMATS if f["format_id"] != "18"])
    assert v.url.endswith("/136") and a.url.endswith("/140")


@pytest.mark.parametrize("bad,msg", [
    ({"is_live": True, "duration": None}, "Live"),
    ({"duration": None}, "no fixed length"),
    ({"_type": "playlist", "entries": []}, "playlist"),
])
def test_parse_info_rejects(bad, msg):
    with pytest.raises(media_info.InfoError, match=msg):
        media_info.parse_info(bad)


def test_selected_streams():
    v, a = media_info.selected_streams({"requested_formats": [FORMATS[5], FORMATS[1]]})
    assert v.vcodec.startswith("avc1") and a.acodec.startswith("mp4a")
    v, a = media_info.selected_streams(dict(FORMATS[1]))
    assert v is None and a.url.endswith("/140")


@pytest.mark.parametrize("raw,needle", [
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "private"),
    ("ERROR: Sign in to confirm your age", "age-restricted"),
    ("ERROR: Video unavailable", "unavailable"),
    ("ERROR: Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>", "internet"),
    ("something weird", "Couldn't load"),
])
def test_friendly_error(raw, needle):
    assert needle.lower() in media_info.friendly_error(raw).lower()


def test_settings_migrates_glass_flag(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"glass": True}))
    assert settings.load(p).appearance == "frosted"
    p.write_text(json.dumps({"glass": False, "opacity": 9, "cookies": "netscape"}))
    s = settings.load(p)
    assert s.appearance == "solid" and s.opacity == 1.0 and s.cookies is None


def test_site_of():
    assert media_info.site_of("https://youtu.be/dQw4w9WgXcQ") == "youtube"
    assert media_info.site_of("https://www.instagram.com/reel/abc/") == "instagram"
    assert media_info.site_of("https://twitter.com/a/status/1") == "x"
    assert media_info.site_of("https://vimeo.com/1") is None


def test_playlist_post_uses_first_video():
    info = {"_type": "playlist", "title": "Post", "uploader": "someone", "entries": [
        {"title": "Image", "vcodec": "none", "url": "https://x/img"},
        {"id": "v1", "duration": 12.5, "formats": FORMATS}]}
    vi = media_info.parse_info(info)
    assert vi.id == "v1" and vi.duration == 12.5 and vi.channel == "someone"


def test_hls_only_formats_get_a_preview():
    hls = [{"format_id": "hls-720", "url": "https://v/720.m3u8", "protocol": "m3u8_native", "vcodec": "avc1",
            "acodec": "mp4a", "height": 720, "ext": "mp4", "tbr": 2000}]
    v, a = media_info.pick_preview(hls)
    assert v is not None and v.url.endswith(".m3u8") and a is None


def test_long_post_titles_are_trimmed():
    t = media_info._title({"title": "x" * 200})
    assert len(t) <= 91 and t.endswith("…")


@pytest.mark.parametrize("raw,needle", [
    ("ERROR: [Instagram] abc: Requested content is not available, rate-limit reached or login required", "signed in"),
    ("ERROR: [twitter] 123: No video could be found in this tweet", "doesn't have a video"),
])
def test_friendly_errors_social(raw, needle):
    assert needle in media_info.friendly_error(raw)


def test_cookie_option():
    assert media_info.ydl_base_opts(None, "firefox")["cookiesfrombrowser"] == ("firefox",)
    assert "cookiesfrombrowser" not in media_info.ydl_base_opts(None, "netscape")


# ---------------------------------------------------------------- dubbed / translated audio tracks
def _dub_formats(mark_original=True):
    from clipdl.core import media_info  # noqa: F401
    en_note = "English original, medium" if mark_original else "English, medium"
    return [
        {"format_id": "18", "url": "http://a/18", "protocol": "https", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a",
         "height": 360},
        {"format_id": "136", "url": "http://a/136", "protocol": "https", "ext": "mp4", "vcodec": "avc1",
         "acodec": "none", "height": 720},
        {"format_id": "140-pt", "url": "http://a/pt", "protocol": "https", "ext": "m4a", "vcodec": "none",
         "acodec": "mp4a", "abr": 130, "language": "pt-BR", "language_preference": 5,
         "format_note": "Portuguese (Brazil) (default), medium"},
        {"format_id": "140-en", "url": "http://a/en", "protocol": "https", "ext": "m4a", "vcodec": "none",
         "acodec": "mp4a", "abr": 128, "language": "en", "language_preference": 10 if mark_original else -1,
         "format_note": en_note},
        {"format_id": "140-es", "url": "http://a/es", "protocol": "https", "ext": "m4a", "vcodec": "none",
         "acodec": "mp4a", "abr": 128, "language": "es", "language_preference": -1,
         "format_note": "Spanish dubbed-auto, medium"},
    ]


def test_original_audio_is_picked_over_dubs():
    from clipdl.core import media_info
    fs = _dub_formats()
    assert media_info.guess_audio_lang(fs) == "en"
    tracks = media_info.audio_tracks(fs)
    assert tracks[0][0] == "en" and tracks[0][2] is True
    assert any("dubbed" in t[1].lower() for t in tracks if t[0] == "es")
    v, a = media_info.pick_preview(fs, "en")
    assert a is not None and a.url == "http://a/en"  # never the dubbed default
    v, a = media_info.pick_preview(fs, "pt-BR")
    assert a.url == "http://a/pt"


def test_single_track_needs_no_choice():
    from clipdl.core import media_info
    fs = [f for f in _dub_formats() if f.get("language") in (None, "en")]
    assert media_info.guess_audio_lang(fs) is None


def test_ytdlp_format_pins_language():
    import yt_dlp
    sel = encode.ytdlp_format(OutputSettings(), False, "en")
    assert 'ba[language="en"]' in sel
    info = {"id": "t", "title": "t", "formats": _dub_formats(mark_original=False), "extractor": "generic",
            "webpage_url": "http://a", "extractor_key": "Generic"}
    with yt_dlp.YoutubeDL({"quiet": True, "format": sel, "simulate": True}) as y:
        r = y.process_ie_result(info, download=False)
    assert r["format_id"].endswith("140-en")
    assert encode.ytdlp_format(OutputSettings(format="mp3"), True, "en") == 'ba[language="en"]/ba/b'


@pytest.mark.parametrize("url,expected", [
    ("https://soundcloud.com/artist-name/track-name", "https://soundcloud.com/artist-name/track-name"),
    ("soundcloud.com/artist/track?si=abc&utm_source=clipboard", "https://soundcloud.com/artist/track"),
    ("https://m.soundcloud.com/artist/track", "https://soundcloud.com/artist/track"),
    ("https://soundcloud.com/artist/track/s-AbC123", "https://soundcloud.com/artist/track/s-AbC123"),
    ("https://soundcloud.com/artist/track?in=artist/sets/album", "https://soundcloud.com/artist/track"),
    ("https://on.soundcloud.com/AbCdEf123", "https://on.soundcloud.com/AbCdEf123"),
    ("https://soundcloud.com/artist", None),
    ("https://soundcloud.com/artist/sets/album", None),
    ("https://soundcloud.com/artist/likes", None),
    ("https://soundcloud.com/discover/sets/weekly", None),
    ("https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("https://vimeo.com/1", None),
])
def test_clean_audio_url(url, expected):
    assert media_info.clean_audio_url(url)[0] == expected


def test_soundcloud_is_audio_only():
    assert media_info.site_of("https://soundcloud.com/a/b") == "soundcloud"
    assert media_info.clean_url("https://soundcloud.com/a/b") == (None, False)  # the video clipper can't use it
