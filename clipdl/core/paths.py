"""File-system locations: assets, settings, ffmpeg (no Qt imports)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Clippr"
OLD_APP_NAME = "ClipDownloader"  # settings from before the rename are moved over once
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"


def app_root() -> Path:
    """Folder that holds ``assets/`` and ``bin/`` (works in a PyInstaller build)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    return app_root() / "assets"


def settings_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    new = base / APP_NAME
    old = base / OLD_APP_NAME
    if not new.exists() and old.is_dir():
        try:
            shutil.copytree(old, new)
        except OSError:
            pass
    return new


def default_download_dir() -> Path:
    return Path.home() / "Downloads"


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def find_tool(name: str) -> str | None:
    """Return a path to ``ffmpeg``/``ffprobe``: bundled ``bin/`` first, then PATH."""
    candidates = [app_root() / "bin" / _exe(name)]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "bin" / _exe(name))
        if IS_MAC:  # Clip Downloader.app/Contents/MacOS -> Contents/Resources/bin
            candidates.append(exe_dir.parent / "Resources" / "bin" / name)
    for c in candidates:
        if c.is_file():
            return str(c)
    found = shutil.which(name)
    if found:
        return found
    if IS_MAC:  # apps started from Finder don't get the shell's PATH, so look where Homebrew / MacPorts install
        for d in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"):
            c = Path(d) / name
            if c.is_file() and os.access(c, os.X_OK):
                return str(c)
    return None


def ffmpeg_path() -> str | None:
    return find_tool("ffmpeg")


def ffprobe_path() -> str | None:
    return find_tool("ffprobe")


def ffmpeg_source() -> str:
    """'bundled', 'path' or 'missing' — shown in the status bar tooltip."""
    p = ffmpeg_path()
    if not p:
        return "missing"
    return "bundled" if Path(p).parent.name == "bin" and str(app_root()) in p else "path"


def reveal(path: str) -> None:
    """Show a file in Explorer / Finder (selected), or open its folder elsewhere."""
    import subprocess
    p = os.path.normpath(path)
    try:
        if IS_WIN:
            subprocess.Popen(["explorer", "/select,", p])
            return
        if IS_MAC:
            subprocess.Popen(["open", "-R", p])
            return
        subprocess.Popen(["xdg-open", str(Path(p).parent if Path(p).is_file() else p)])
    except OSError:
        pass


def open_folder(folder: str) -> None:
    import subprocess
    try:
        if IS_WIN:
            os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606
        elif IS_MAC:
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except OSError:
        pass


def file_manager() -> str:
    return "Explorer" if IS_WIN else ("Finder" if IS_MAC else "your file manager")
