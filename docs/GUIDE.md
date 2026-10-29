# Clippr: full guide

Paste a YouTube, Instagram or X link, watch it in the app, mark a start and end, and export exactly that part as MP4, WebM, MOV, GIF or MP3.

Everything lives in one window. The **session menu** next to the app name (or Ctrl+1 … Ctrl+5) switches between Clip Video and four more tools; each session keeps its queue and settings while you're elsewhere, and the app reopens on the session you used last:

| Tool | What it does |
| --- | --- |
| **To MP3** | Saves the audio from YouTube / Instagram / X links as MP3, M4A, WAV, FLAC or Opus, with cover art and tags. Paste many links at once. |
| **Convert** | One converter for everything. Video and audio go to MP4, MKV, WebM, MOV, AVI, GIF, MP3, M4A, WAV, FLAC, OGG or Opus; pictures go to PNG, JPG, WebP, HEIC, BMP, TIFF, GIF or ICO (HEIC/iPhone photos open too). Each kind has its own target, so a mixed list converts in one go; animated GIFs count as video. |
| **Resize** | Batch resize (percent, fit, exact with a lock-aspect chain, crop-to-fill) plus a Photoshop-style editor: move, scale, rotate and flip the picture on its canvas, and crop or extend the canvas. |
| **Compress** | Shrinks PDFs (recompresses the images inside), pictures, videos and audio; anything else becomes a ZIP. Shows before → after. |

Every tool takes drag & drop (files or whole folders, with an animated drop target), runs a queue with a live progress bar per item, and remembers its settings.

**Paste from the web:** in Convert, Resize and Compress, right-click a picture in your browser → *Copy image* (or copy its address) and press **Ctrl+V** or the **Paste** button. Dragging a picture out of the browser works too. The original file is downloaded when possible; otherwise the copied picture is used. Pasted pictures are saved in `Downloads\Pasted images`. Finished pictures have a **Copy** button so you can paste the result anywhere.

**Resize editor:** click a picture in the list to edit it.

| Do this | How |
| --- | --- |
| Move the picture | Drag it (snaps to the canvas edges and centre; hold Ctrl to move freely). Arrow keys nudge 1 px, Shift+arrows 10 px |
| Scale | Drag a white handle. Proportions follow the chain button; hold Shift to do the opposite, Alt to scale from the centre |
| Rotate | Drag the round knob, or just outside a corner. Shift snaps to 15° steps. Or type an angle |
| Crop / extend the canvas | Drag the tabs just outside the canvas edges |
| Resize everything | Type W or H in the editor bar (the chain keeps proportions) |
| Fit · Fill · Crop to image | Fit the picture inside the canvas, cover it, or shrink the canvas to the picture |
| Background | Clear (transparent), White or Black for empty canvas |
| Undo / redo | Ctrl+Z / Ctrl+Shift+Z |
| Zoom / pan | Mouse wheel / drag empty space; double-click empty space to fit |

Edited pictures are marked **Custom** and use their own canvas; **Reset** puts one back on the batch settings, and **Apply to all** copies the canvas and placement to every waiting picture.

## Install it (Windows)

Run **`Clip-Downloader-Setup-<version>.exe`** from `dist\installer`. It installs for your user account (no admin prompt), adds **Clip Downloader** to the Start menu and the Desktop, and shows up in *Settings › Apps* for uninstalling. ffmpeg is bundled.

To build the installer yourself, double-click **`make_installer.bat`** (or `make_installer.bat /install` to build and install in one go). The first run sets up Python packages, downloads ffmpeg and installs Inno Setup for your user; later runs just rebuild.

## Install it (macOS)

On a Mac with Python 3.12+: `bash packaging/mac/build_mac.sh`. You get `dist/Clip-Downloader-<version>-<arch>.dmg`; open it and drag **Clip Downloader** into Applications. ffmpeg is bundled (a static build, no Homebrew needed). The build is ad-hoc signed, so the first time macOS may say it can't verify the developer: right-click the app › **Open** › **Open** (once).

No Mac to build on? Push this folder to GitHub, copy `packaging/ci/github-build.yml` to `.github/workflows/build.yml`, and run **Actions › Build installers**. It builds the Windows installer plus Apple Silicon and Intel disk images and lets you download them.

On a Mac the window keeps the usual red/yellow/green buttons, shortcuts use ⌘ instead of Ctrl, Frosted uses the system blur, settings live in `~/Library/Application Support/ClipDownloader`, and Safari can supply sign-in cookies (it needs Full Disk Access).

## Run from source

Windows:

1. Double-click **`setup.bat`** once. It creates a `.venv` folder and installs everything (PySide6, yt-dlp, …).
2. Double-click **`Clip Downloader.bat`** to start.

macOS: double-click **`setup.command`** once, then **`Clip Downloader.command`** (or `brew install ffmpeg` first if you don't have it).

ffmpeg is required. The app uses `bin\ffmpeg.exe` (`bin/ffmpeg` on a Mac) if you put one there; otherwise ffmpeg from your PATH (on a Mac also Homebrew's folders). The two dots in the bottom-right corner turn red if yt-dlp or ffmpeg is missing.

From a terminal: `.venv\Scripts\python run.py` (`.venv/bin/python run.py` on a Mac). Add `--solid` to start with glass off, or `--reset-settings` to start fresh.

The old app is untouched: `clip_downloader.py` still works on its own.

## Using it

| Do this | How |
| --- | --- |
| Load a video | Paste a link (Ctrl+V anywhere), drop a link from your browser onto the window, or type it and press Enter |
| Play / pause | Space, or the play button |
| Mark the clip while watching | **I** = set start, **O** = set end (or the Set start / Set end buttons) |
| Drag the clip | Drag a green handle (paused: the preview jumps to that frame); drag inside the green area to move the whole clip |
| Exact times | Type `90`, `1:30` or `1:02:30.5` in Start / End; − and + nudge 1 s (Shift: 0.1 s) |
| Preview the clip | **Loop clip** (L) replays just your selection. It's off by default; outside the clip the whole video always plays |
| Seek | ← / → 5 s, Shift+← / → about one frame, Home / End jump to clip start / end |
| Fullscreen preview | F (Esc to exit) |
| Download | Ctrl+Enter or **Download clip**; Cancel at any time leaves no partial files |
| Open the save folder | Ctrl+Shift+O |

**Output tab:** format, resolution, frame rate, codec, quality and audio. Videos with dubbed or AI-translated audio (some YouTube videos and reels) use the original language; an **Audio language** menu appears so you can pick another track. The estimate row shows the approximate size and whether the clip will be a fast **stream copy** or a **re-encode**. Frame rates above the source repeat frames; they don't create smoother motion.

**Appearance** (sliders button in the title bar): **Solid**, **Frosted** (blurred desktop behind the window) or **Clear** (see straight through, like a transparent Terminal). The opacity slider thins out the window and its panels together.

**Sign-in cookies** (same popover): some Instagram and X videos need you to be logged in. Pick the browser you're signed in with (Firefox works best; close Chrome/Edge first if it complains).

Settings are remembered in `%APPDATA%\ClipDownloader\settings.json` (macOS: `~/Library/Application Support/ClipDownloader`).

## Build a standalone app without an installer

`.\build.ps1` produces `dist\Clip Downloader\Clip Downloader.exe` plus a zip, and bundles ffmpeg from `bin\` or your PATH.

## Project layout

```
run.py                  entry point
clipdl/app.py           QApplication setup
clipdl/controller.py    state machine: Empty → Loading → Ready → Downloading → Done / Error
clipdl/core/            no Qt: time parsing, settings, ffmpeg args, media info, clip pipeline, waveform
clipdl/workers/jobs.py  QThreadPool jobs (info, waveform, clip) reporting through signals
clipdl/ui/              window, glass, player, trim track, export / progress panels, theme
tests/                  pytest suites + ui_smoke.py (renders every screen offscreen)
```

How a download works: yt-dlp finds the stream URLs for your settings, then ffmpeg seeks straight to your start time and cuts and encodes just that range in one pass. Its progress output drives the live bar. If that direct route fails, the app falls back to yt-dlp's own section download and then encodes the file.

## Tests

```
.venv\Scripts\python -m pytest -q
```

## If something breaks

- **"YouTube changed something" / 403 errors:** update yt-dlp: `.venv\Scripts\python -m pip install -U yt-dlp`.
- **Window looks odd see-through:** switch to Solid in the appearance popover, or start with `--solid`.
- **Instagram / X says "sign in":** set Sign-in cookies to your browser and try again.
- **No preview, but downloads work:** the preview player needs Qt Multimedia's FFmpeg backend, which ships with PySide6 on Windows.

Fonts: Inter / Inter Display (an SF-style typeface) and Geist Mono, both under the SIL Open Font License (`assets/fonts/*-OFL.txt`).
PDF compression uses PyMuPDF, which is AGPL-3.0: fine for personal use; check its license before selling or distributing the app.
