#!/bin/bash
# macOS one-time setup (double-click in Finder): creates .venv and installs the requirements.
cd "$(dirname "$0")"
PY=python3
command -v "$PY" >/dev/null || { echo "Install Python 3.12+ from https://www.python.org/downloads/macos/ first."; read -r; exit 1; }
"$PY" -m venv .venv && .venv/bin/python -m pip install --upgrade pip -q && .venv/bin/python -m pip install -r requirements.txt
if ! command -v ffmpeg >/dev/null && [ ! -x bin/ffmpeg ] && [ ! -x /opt/homebrew/bin/ffmpeg ] && [ ! -x /usr/local/bin/ffmpeg ]; then
  echo
  echo "NOTE: ffmpeg wasn't found. Install it with Homebrew (brew install ffmpeg) or put ffmpeg + ffprobe in a 'bin' folder here."
fi
echo
echo "Done. Double-click 'Clip Downloader.command' to start."
read -r -p "Press Return to close."
