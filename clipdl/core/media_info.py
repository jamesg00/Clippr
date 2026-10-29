"""Video info: URL checks, yt-dlp extraction, preview stream choice (no Qt imports)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
             "www.youtube-nocookie.com", "youtube-nocookie.com")
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class InfoError(Exception):
    """User-facing extraction error (message is safe to show)."""


_IG_HOSTS = ("instagram.com", "www.instagram.com", "m.instagram.com")
_X_HOSTS = ("x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com", "mobile.x.com")
_SC_HOSTS = ("soundcloud.com", "www.soundcloud.com", "m.soundcloud.com")
_SC_SHORT = ("on.soundcloud.com",)
# first path parts that are SoundCloud pages, not artists; second parts that are lists, not tracks
_SC_NOT_USER = {"discover", "stations", "search", "you", "charts", "upload", "settings", "messages", "notifications",
                "pages", "terms-of-use", "pro", "mobile", "feed", "people", "tags", "imprint", "jobs", "popular"}
_SC_NOT_TRACK = {"sets", "tracks", "albums", "reposts", "likes", "spotlight", "comments", "popular-tracks",
                 "followers", "following", "recommended", "toptracks"}
SITE_NAMES = {"youtube": "YouTube", "instagram": "Instagram", "x": "X", "soundcloud": "SoundCloud"}


def _parse(url: str):
    url = (url or "").strip()
    if not url:
        return None
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "https://" + url
    try:
        return urlparse(url)
    except ValueError:
        return None


def _clean_youtube(u) -> tuple[str | None, bool]:
    host = (u.hostname or "").lower()
    q = parse_qs(u.query)
    had_list = "list" in q
    vid = None
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif u.path == "/watch":
        vid = (q.get("v") or [None])[0]
    else:
        m = re.match(r"^/(shorts|embed|live|v)/([^/?#]+)", u.path)
        if m:
            vid = m.group(2)
    if not vid or not _ID.match(vid):
        return None, had_list
    t = (q.get("t") or q.get("start") or [None])[0]
    query = {"v": vid}
    if t:
        query["t"] = t
    return urlunparse(("https", "www.youtube.com", "/watch", "", urlencode(query), "")), had_list


def _clean_instagram(u) -> tuple[str | None, bool]:
    m = re.match(r"^/(?:[A-Za-z0-9_.]+/)?(p|reel|reels|tv)/([A-Za-z0-9_-]+)", u.path)
    if not m:
        return None, False
    kind = "reel" if m.group(1) in ("reel", "reels") else m.group(1)
    return f"https://www.instagram.com/{kind}/{m.group(2)}/", False


def _clean_x(u) -> tuple[str | None, bool]:
    m = re.match(r"^/([A-Za-z0-9_]{1,15}|i(?:/web)?)/status(?:es)?/(\d+)", u.path)
    if not m:
        return None, False
    user = "i" if m.group(1) in ("i", "i/web") else m.group(1)
    return f"https://x.com/{user}/status/{m.group(2)}", False


def _clean_soundcloud(u) -> tuple[str | None, bool]:
    """A single SoundCloud track (sets, profiles and likes are lists, so they're refused)."""
    host = (u.hostname or "").lower()
    had_list = "in" in parse_qs(u.query)
    if host in _SC_SHORT:  # share link, yt-dlp follows the redirect
        code = u.path.strip("/").split("/")[0]
        return (f"https://on.soundcloud.com/{code}", False) if re.match(r"^[A-Za-z0-9_-]+$", code) else (None, False)
    parts = [p for p in u.path.split("/") if p]
    if len(parts) not in (2, 3) or parts[0].lower() in _SC_NOT_USER or parts[1].lower() in _SC_NOT_TRACK:
        return None, had_list
    if not all(re.match(r"^[\w-]+$", p) for p in parts[:2]):
        return None, had_list
    if len(parts) == 3 and not re.match(r"^s-[A-Za-z0-9]+$", parts[2]):  # only a private-link token may follow
        return None, had_list
    return "https://soundcloud.com/" + "/".join(parts), had_list


def site_of(url: str) -> str | None:
    """'youtube' | 'instagram' | 'x' | 'soundcloud' | None"""
    u = _parse(url)
    if u is None:
        return None
    host = (u.hostname or "").lower()
    if host in _YT_HOSTS:
        return "youtube"
    if host in _IG_HOSTS:
        return "instagram"
    if host in _X_HOSTS:
        return "x"
    if host in _SC_HOSTS or host in _SC_SHORT:
        return "soundcloud"
    return None


def clean_url(url: str) -> tuple[str | None, bool]:
    """Return (canonical URL or None, had_playlist) for YouTube, Instagram and X links."""
    u = _parse(url)
    if u is None:
        return None, False
    site = site_of(url)
    if site == "youtube":
        return _clean_youtube(u)
    if site == "instagram":
        return _clean_instagram(u)
    if site == "x":
        return _clean_x(u)
    return None, False


def clean_audio_url(url: str) -> tuple[str | None, bool]:
    """clean_url plus audio-only sites (SoundCloud), for the To MP3 tool."""
    clean, had_list = clean_url(url)
    if clean:
        return clean, had_list
    u = _parse(url)
    if u is not None and site_of(url) == "soundcloud":
        return _clean_soundcloud(u)
    return None, False


def video_id(url: str) -> str | None:
    clean, _ = clean_url(url)
    if not clean:
        return None
    if site_of(clean) == "youtube":
        return parse_qs(urlparse(clean).query)["v"][0]
    return clean.rstrip("/").split("/")[-1]


@dataclass
class Stream:
    url: str
    headers: dict = field(default_factory=dict)
    vcodec: str | None = None
    acodec: str | None = None
    height: int | None = None
    fps: float | None = None
    tbr: float | None = None  # kbps
    ext: str | None = None


@dataclass
class VideoInfo:
    id: str
    title: str
    channel: str
    duration: float
    thumbnail: str | None
    webpage_url: str
    heights: list[int]
    max_height: int | None
    fps: float | None
    preview_video: Stream | None = None
    preview_audio: Stream | None = None  # None when preview_video is muxed
    waveform_audio: Stream | None = None  # smallest audio-only stream
    audio_tracks: list = field(default_factory=list)  # [(lang, label, is_original)] when there are several
    audio_lang: str | None = None  # the track we'll use (original language), None = only one track
    formats: list = field(default_factory=list, repr=False)  # raw yt-dlp formats, to re-pick the preview


def _is_http(f: dict) -> bool:
    return (f.get("protocol") or "").startswith("http") and bool(f.get("url"))


def _is_playable(f: dict) -> bool:
    """Direct HTTP or HLS (X serves most videos as HLS)."""
    return bool(f.get("url")) and ((f.get("protocol") or "").startswith(("http", "m3u8")))


def _stream(f: dict) -> Stream:
    return Stream(url=f["url"], headers=dict(f.get("http_headers") or {}),
                  vcodec=f.get("vcodec"), acodec=f.get("acodec"),
                  height=f.get("height"), fps=f.get("fps"), tbr=f.get("tbr"), ext=f.get("ext"))


def _has_v(f):
    return (f.get("vcodec") or "none") != "none"


def _has_a(f):
    return (f.get("acodec") or "none") != "none"


def _note(f: dict) -> str:
    return (f.get("format_note") or "").lower()


def _is_dub(f: dict) -> bool:
    n = _note(f)
    return "dub" in n or "translat" in n


def _audio_score(f: dict, lang: str | None):
    """Higher is better: the wanted language, then the original track, then not dubbed."""
    return ((lang is None or f.get("language") == lang),
            (f.get("language_preference") or 0) >= 10 or "original" in _note(f),
            not _is_dub(f),
            f.get("language_preference") or 0)


def audio_tracks(formats: list[dict]) -> list[tuple[str, str, bool]]:
    """Distinct audio languages [(lang, label, is_original)], only meaningful when there are 2+."""
    seen: dict[str, tuple[str, str, bool]] = {}
    for f in formats:
        lang = f.get("language")
        if not lang or not _has_a(f):
            continue
        name = (f.get("format_note") or "").split(",")[0]
        for junk in ("(default)", "(original)", "original", "default"):
            name = name.replace(junk, "")
        name = " ".join(name.split()) or lang
        if name.lower() in ("low", "medium", "high", "ultralow", "tiny"):
            name = lang
        orig = (f.get("language_preference") or 0) >= 10 or "original" in _note(f)
        prev = seen.get(lang)
        if prev is None or (orig and not prev[2]):
            seen[lang] = (lang, name + (" (dubbed)" if _is_dub(f) and "dub" not in name.lower() else ""), orig)
    tracks = list(seen.values())
    tracks.sort(key=lambda t: (not t[2], "dub" in t[1].lower(), t[1].lower()))
    return tracks


def guess_audio_lang(formats: list[dict]) -> str | None:
    """The original-language audio track when a video has dubbed / translated ones, else None."""
    tracks = audio_tracks(formats)
    if len(tracks) < 2:
        return None
    for lang, _, orig in tracks:
        if orig:
            return lang
    # a progressive (video+audio) file usually carries the original audio
    for f in formats:
        if _has_v(f) and _has_a(f) and f.get("language") and not _is_dub(f):
            return f["language"]
    clean = [t for t in tracks if "dub" not in t[1].lower()]
    if len(clean) == 1:
        return clean[0][0]
    auds = [f for f in formats if _has_a(f) and f.get("language")]
    auds.sort(key=lambda f: (not _is_dub(f), f.get("language_preference") or 0), reverse=True)
    return auds[0]["language"] if auds else None


def pick_preview(formats: list[dict], lang: str | None = None) -> tuple[Stream | None, Stream | None]:
    """Prefer a muxed MP4 (format 18); else best H.264 <= 720p + best m4a audio (in the chosen language)."""
    fs = [f for f in formats if _is_http(f)] or [f for f in formats if _is_playable(f)]
    vids = [f for f in fs if _has_v(f) and not _has_a(f) and (f.get("height") or 0) <= 720]
    vids.sort(key=lambda f: (str(f.get("vcodec") or "").startswith("avc1"), f.get("height") or 0,
                             f.get("tbr") or 0), reverse=True)
    auds = [f for f in fs if _has_a(f) and not _has_v(f)]
    auds.sort(key=lambda f: (_audio_score(f, lang), f.get("ext") == "m4a", f.get("abr") or f.get("tbr") or 0),
              reverse=True)
    lang_auds = bool(lang) and any(a.get("language") == lang for a in auds)
    muxed = [f for f in fs if _has_v(f) and _has_a(f) and (f.get("height") or 0) <= 720
             and (lang is None or f.get("language") == lang or (f.get("language") is None and not lang_auds))]
    muxed.sort(key=lambda f: ((f.get("ext") == "mp4"), f.get("height") or 0, f.get("tbr") or 0), reverse=True)
    if muxed:
        return _stream(muxed[0]), None
    if vids and auds:
        return _stream(vids[0]), _stream(auds[0])
    if vids:
        return _stream(vids[0]), None
    return None, None


def pick_waveform_audio(formats: list[dict], lang: str | None = None) -> Stream | None:
    auds = [f for f in formats if _is_playable(f) and _has_a(f) and not _has_v(f)]
    if not auds:
        auds = [f for f in formats if _is_playable(f) and _has_a(f)]
    if not auds:
        return None
    auds.sort(key=lambda f: (not _audio_score(f, lang)[0], f.get("abr") or f.get("tbr") or 1e9))
    return _stream(auds[0])


def _first_video_entry(info: dict) -> dict | None:
    for e in info.get("entries") or []:
        if isinstance(e, dict) and (e.get("formats") or e.get("url")) and e.get("vcodec", "x") != "none":
            return e
    return None


def parse_info(info: dict) -> VideoInfo:
    if info.get("_type") == "playlist" or info.get("entries") is not None:
        # Instagram carousels and X posts with several videos come back as playlists: use the first video
        entry = _first_video_entry(info)
        if entry is None:
            raise InfoError("That link is a playlist or a post without a video. Paste a link to a single video.")
        entry = dict(entry)
        entry.setdefault("title", info.get("title"))
        entry.setdefault("uploader", info.get("uploader"))
        info = entry
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise InfoError("Live streams aren't supported yet.")
    duration = info.get("duration")
    if not duration:
        raise InfoError("This video has no fixed length, so it can't be clipped.")
    formats = info.get("formats") or []
    heights = sorted({int(f["height"]) for f in formats if _has_v(f) and f.get("height")})
    fpss = [f.get("fps") for f in formats if _has_v(f) and f.get("fps")]
    lang = guess_audio_lang(formats)
    tracks = audio_tracks(formats) if lang else []
    pv, pa = pick_preview(formats, lang)
    return VideoInfo(
        id=info.get("id") or "",
        title=_title(info),
        channel=info.get("channel") or info.get("uploader") or info.get("uploader_id") or "",
        duration=float(duration),
        thumbnail=info.get("thumbnail"),
        webpage_url=info.get("webpage_url") or "",
        heights=heights,
        max_height=heights[-1] if heights else None,
        fps=float(max(fpss)) if fpss else None,
        preview_video=pv,
        preview_audio=pa,
        waveform_audio=pick_waveform_audio(formats, lang),
        audio_tracks=tracks,
        audio_lang=lang,
        formats=formats,
    )


def _title(info: dict) -> str:
    t = (info.get("title") or "").strip()
    if not t or t.lower().startswith(("video by", "post by")) and info.get("description"):
        t = (info.get("description") or t or "").strip()
    t = re.sub(r"https?://\S+", "", t).replace("\n", " ").strip()
    return (t[:90].rstrip() + "…") if len(t) > 90 else (t or "clip")


def friendly_error(msg: str) -> str:
    """Map raw yt-dlp error text to a short message for the UI."""
    m = (msg or "").lower()
    if "private video" in m:
        return "This video is private."
    if ("instagram" in m and ("login" in m or "log in" in m or "rate-limit" in m or "not available" in m)) or \
            "you need to log in" in m:
        return "Instagram wants you signed in. Pick your browser under Settings → Sign-in cookies and try again."
    if "no video could be found in this tweet" in m or "no video" in m and "tweet" in m:
        return "That post doesn't have a video."
    if ("twitter" in m or "x.com" in m) and ("login" in m or "authorization" in m or "suspended" in m or "nsfw" in m):
        return "X wants you signed in for this post. Pick your browser under Settings → Sign-in cookies."
    if "could not copy" in m and "cookie" in m or "failed to decrypt" in m:
        return "Couldn't read that browser's cookies. Close the browser, or pick Firefox, and try again."
    if "soundcloud" in m:
        if "geo" in m or "not available in your country" in m:
            return "This SoundCloud track isn't available in your country."
        if "404" in m or "not found" in m or "unable to download json" in m:
            return "This SoundCloud track is private, removed, or the link is wrong."
        if "getaddrinfo" in m or "timed out" in m or "connection" in m:
            return "Couldn't reach SoundCloud. Check your internet connection."
    if "sign in to confirm your age" in m or "age-restricted" in m or "inappropriate for some users" in m:
        return "This video is age-restricted and can't be downloaded without signing in."
    if "sign in to confirm you" in m and "bot" in m:
        return "YouTube is asking for a sign-in check. Try again in a few minutes."
    if "video unavailable" in m or "has been removed" in m or "not available" in m:
        return "This video is unavailable."
    if "members-only" in m or "join this channel" in m:
        return "This video is for channel members only."
    if "unable to download webpage" in m or "getaddrinfo" in m or "timed out" in m or "connection" in m:
        return "Couldn't reach YouTube. Check your internet connection."
    if "http error 403" in m:
        return "YouTube refused the request (403). Try again, or update yt-dlp."
    if "unsupported url" in m:
        return "That link isn't supported. Paste a YouTube, Instagram or X video link."
    if "nsig" in m or "signature" in m or "unable to extract" in m:
        return "YouTube changed something. Update yt-dlp (pip install -U yt-dlp) and try again."
    return "Couldn't load this video."


COOKIE_BROWSERS = ("firefox", "chrome", "edge", "safari", "brave", "opera", "vivaldi")


def ydl_base_opts(ffmpeg: str | None = None, cookies: str | None = None) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
            "socket_timeout": 20, "retries": 3}
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    if cookies in COOKIE_BROWSERS:
        opts["cookiesfrombrowser"] = (cookies,)
    return opts


def fetch_info(url: str, ffmpeg: str | None = None, fmt: str | None = None, cookies: str | None = None) -> dict:
    """Raw yt-dlp info dict (blocking). Raises InfoError with a friendly message."""
    import yt_dlp
    from yt_dlp.utils import DownloadError

    clean, _ = clean_url(url)
    if not clean:
        raise InfoError("That isn't a YouTube, Instagram or X video link.")
    opts = ydl_base_opts(ffmpeg, cookies)
    if fmt:
        opts["format"] = fmt
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(clean, download=False)
    except DownloadError as e:
        raise InfoError(friendly_error(str(e))) from e
    except Exception as e:  # noqa: BLE001 - surface anything as a friendly error
        raise InfoError(friendly_error(str(e))) from e


def selected_streams(info: dict) -> tuple[Stream | None, Stream | None]:
    """After extraction with a format selector: (video stream, audio stream).

    Muxed single format -> (stream, None). Audio-only -> (None, stream).
    """
    if info.get("entries") is not None:
        info = _first_video_entry(info) or {}
    req = info.get("requested_formats")
    if req:
        v = next((f for f in req if _has_v(f)), None)
        a = next((f for f in req if _has_a(f) and not _has_v(f)), None)
        return (_stream(v) if v else None), (_stream(a) if a else None)
    if info.get("url"):
        f = info
        if _has_v(f):
            return _stream(f), None
        return None, _stream(f)
    return None, None
