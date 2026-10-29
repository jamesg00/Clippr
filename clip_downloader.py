"""YouTube Clip Downloader - download just a portion of a video as MP4.

Requires: pip install yt-dlp   (and ffmpeg on PATH)
"""
import os
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import yt_dlp
from yt_dlp.utils import download_range_func


def parse_time(text):
    """Accept 90, 1:30, or 01:01:30 (optionally with .5 fractions). Returns seconds."""
    text = text.strip()
    if not text:
        raise ValueError("empty time")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"bad time: {text}")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + float(p)
    return seconds


def fmt_time(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Clip Downloader")
        self.geometry("560x380")
        self.resizable(False, False)

        self.url = tk.StringVar()
        self.start = tk.StringVar(value="0:00")
        self.end = tk.StringVar(value="0:30")
        self.name = tk.StringVar(value="clip")
        self.folder = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        self.precise = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Paste a YouTube link to get started.")

        pad = {"padx": 10, "pady": 5}
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Video URL:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.url).grid(row=0, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Button(frm, text="Get video info", command=self.fetch_info).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Start (m:ss):").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.start, width=12).grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(frm, text="End (m:ss):").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.end, width=12).grid(row=3, column=1, sticky="w", **pad)

        ttk.Label(frm, text="File name:").grid(row=4, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.name).grid(row=4, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frm, text="Save to:").grid(row=5, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.folder).grid(row=5, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Browse...", command=self.browse).grid(row=5, column=2, **pad)

        ttk.Checkbutton(frm, text="Frame-accurate cut (slower, re-encodes the clip)",
                        variable=self.precise).grid(row=6, column=1, columnspan=2, sticky="w", **pad)

        self.btn = ttk.Button(frm, text="Download clip", command=self.download)
        self.btn.grid(row=7, column=1, sticky="w", **pad)

        self.bar = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.bar.grid(row=8, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(frm, textvariable=self.status, wraplength=520).grid(row=9, column=0, columnspan=3, sticky="w", **pad)

    # ---------- helpers ----------
    def set_status(self, text):
        self.after(0, self.status.set, text)

    def set_progress(self, value):
        self.after(0, self.bar.configure, {"value": value})

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.folder.get())
        if d:
            self.folder.set(d)

    # ---------- info ----------
    def fetch_info(self):
        url = self.url.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Paste a YouTube link first.")
            return
        self.set_status("Fetching video info...")
        threading.Thread(target=self._fetch_info, args=(url,), daemon=True).start()

    def _fetch_info(self, url):
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True}) as ydl:
                info = ydl.extract_info(url, download=False)
            title = info.get("title", "clip")
            dur = info.get("duration") or 0
            safe = re.sub(r'[\\/:*?"<>|]+', "", title)[:80].strip() or "clip"
            self.after(0, self.name.set, safe)
            self.set_status(f"Title: {title}\nLength: {fmt_time(dur)}")
        except Exception as e:
            self.set_status(f"Couldn't get info: {e}")

    # ---------- download ----------
    def download(self):
        url = self.url.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Paste a YouTube link first.")
            return
        try:
            start, end = parse_time(self.start.get()), parse_time(self.end.get())
        except ValueError:
            messagebox.showerror("Bad time", "Use times like 90, 1:30, or 1:02:30.")
            return
        if end <= start:
            messagebox.showerror("Bad time", "End time must be after start time.")
            return
        name = re.sub(r'[\\/:*?"<>|]+', "", self.name.get()).strip() or "clip"
        folder = self.folder.get()
        os.makedirs(folder, exist_ok=True)

        self.btn.configure(state="disabled")
        self.set_progress(0)
        self.set_status(f"Downloading {fmt_time(start)} → {fmt_time(end)} ...")
        threading.Thread(target=self._download,
                         args=(url, start, end, os.path.join(folder, name)),
                         daemon=True).start()

    def _hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                self.set_progress(d.get("downloaded_bytes", 0) / total * 100)
            else:
                # ffmpeg-driven section downloads often don't report size
                self.after(0, lambda: self.bar.configure(mode="indeterminate") or self.bar.start(15))
        elif d["status"] == "finished":
            self.set_status("Finishing up (merging audio + video)...")

    def _download(self, url, start, end, outbase):
        opts = {
            "format": "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b",
            "merge_output_format": "mp4",
            "outtmpl": outbase + ".%(ext)s",
            "download_ranges": download_range_func(None, [(start, end)]),
            "force_keyframes_at_cuts": self.precise.get(),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._hook],
            "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            self.set_status(f"Done! Saved to:\n{outbase}.mp4")
            self.after(0, self._finish, True)
        except Exception as e:
            self.set_status(f"Error: {e}")
            self.after(0, self._finish, False)

    def _finish(self, ok):
        self.bar.stop()
        self.bar.configure(mode="determinate", value=100 if ok else 0)
        self.btn.configure(state="normal")


if __name__ == "__main__":
    App().mainloop()
