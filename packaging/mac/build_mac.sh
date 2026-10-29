#!/bin/bash
# Builds "Clip Downloader.app" and a drag-to-Applications disk image:  dist/Clip-Downloader-<version>-<arch>.dmg
# Run on a Mac (Apple Silicon or Intel) with Python 3.12+:   bash packaging/mac/build_mac.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
PY="${PYTHON:-python3}"
ARCH="$(uname -m)"          # arm64 | x86_64

echo "==> Python environment"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip --disable-pip-version-check -q
.venv/bin/python -m pip install -r requirements.txt --disable-pip-version-check -q
VER="$(.venv/bin/python -c 'import clipdl; print(clipdl.__version__)')"

echo "==> ffmpeg"
mkdir -p bin
if [ ! -x bin/ffmpeg ] || [ ! -x bin/ffprobe ]; then
  # static builds, so the app works on Macs without Homebrew
  FFARCH=$([ "$ARCH" = "arm64" ] && echo arm64 || echo amd64)
  for t in ffmpeg ffprobe; do
    curl -fsSL "https://ffmpeg.martin-riedl.de/redirect/latest/macos/$FFARCH/release/$t.zip" -o "/tmp/$t.zip"
    unzip -o -q "/tmp/$t.zip" -d bin && rm "/tmp/$t.zip"
    chmod +x "bin/$t"
  done
fi

echo "==> Building Clip Downloader $VER ($ARCH)"
.venv/bin/python -m PyInstaller --noconfirm --clean --windowed \
  --name "Clip Downloader" \
  --icon assets/app.png \
  --osx-bundle-identifier com.clipdownloader.app \
  --add-data "assets:assets" \
  --add-data "clipdl/qml_ui/qml:clipdl/qml_ui/qml" \
  --collect-submodules qframelesswindow \
  --collect-all pillow_heif \
  --collect-all pymupdf \
  --exclude-module tkinter \
  run.py

APP="dist/Clip Downloader.app"
mkdir -p "$APP/Contents/Resources/bin"
cp bin/ffmpeg bin/ffprobe "$APP/Contents/Resources/bin/"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" "$APP/Contents/Info.plist" || true
/usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string 11.0" "$APP/Contents/Info.plist" 2>/dev/null || true
# ad-hoc signature (required on Apple Silicon); for public distribution sign with a Developer ID and notarize
codesign --force --deep --sign - "$APP"

echo "==> Disk image"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="dist/Clip-Downloader-$VER-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname "Clip Downloader" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "Done: $DMG  (open it and drag Clip Downloader into Applications)"
