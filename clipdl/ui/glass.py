"""Window backdrop modes: "solid", "frosted" (blurred desktop) and "clear" (see-through, Terminal-style).

* macOS   — the window has a per-pixel-alpha surface; Frosted adds an NSVisualEffectView behind it, Clear just
            lets the painted tint show the desktop.

* Frosted — Windows 11 22H2+: DWM acrylic backdrop · Windows 11 21H2: Mica · Windows 10: blur-behind accent.
* Clear   — Windows 10/11: transparent accent, no blur; the app paints its own tint at the chosen opacity.
* Solid   — no effect.

Fix for stale caption buttons: the frame is never extended into the title-bar area (top margin 0), and every
switch forces a frame change + full redraw so Windows can't leave its own min/max/close glyphs behind.
Every call is wrapped; a failing effect falls back to "solid" instead of crashing.
"""
from __future__ import annotations

import sys

MODES = ("solid", "frosted", "clear")


def windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:  # noqa: BLE001
        return 0


def platform_kind() -> str:
    if sys.platform == "darwin":
        return "mac"
    b = windows_build()
    if not b:
        return "other"
    return "win11" if b >= 22000 else "win10"


def supported() -> bool:
    return platform_kind() in ("win10", "win11", "mac")


def default_mode() -> str:
    return "frosted" if supported() else "solid"


def _mac_apply(window, mode: str) -> str:
    """macOS: real see-through needs the translucent surface set up in GlassWindow; Frosted adds the system blur."""
    from PySide6.QtCore import Qt
    if mode == "solid" or not window.testAttribute(Qt.WA_TranslucentBackground):
        _mac_blur(window, False)
        return "solid"
    if mode == "frosted":
        return "frosted" if _mac_blur(window, True) else "clear"
    _mac_blur(window, False)
    return "clear"


def _mac_blur(window, on: bool) -> bool:
    view = getattr(window, "_mac_blur_view", None)
    if view is not None:
        try:
            view.setHidden_(not on)
            return True
        except Exception:  # noqa: BLE001
            return False
    if not on:
        return True
    try:
        import Cocoa
        import objc
        ns_view = objc.objc_object(c_void_p=int(window.winId()))
        content = ns_view.window().contentView()
        fx = Cocoa.NSVisualEffectView.alloc().initWithFrame_(content.bounds())
        fx.setAutoresizingMask_(Cocoa.NSViewWidthSizable | Cocoa.NSViewHeightSizable)
        fx.setBlendingMode_(Cocoa.NSVisualEffectBlendingModeBehindWindow)
        fx.setMaterial_(Cocoa.NSVisualEffectMaterialHUDWindow)
        fx.setState_(Cocoa.NSVisualEffectStateActive)
        fx.setAppearance_(Cocoa.NSAppearance.appearanceNamed_(Cocoa.NSAppearanceNameVibrantDark))
        content.addSubview_positioned_relativeTo_(fx, Cocoa.NSWindowBelow, None)
        window._mac_blur_view = fx
        return True
    except Exception:  # noqa: BLE001
        return False


def describe(mode: str) -> str:
    k = platform_kind()
    if mode == "frosted":
        return "Frosted (acrylic)" if k == "win11" else "Frosted (blur)"
    return {"clear": "Clear (see-through)", "solid": "Solid"}.get(mode, mode)


# ---------------------------------------------------------------- win32 plumbing
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_NONE, DWMSBT_MAINWINDOW, DWMSBT_TRANSIENTWINDOW = 1, 2, 3
ACCENT_DISABLED, ACCENT_TRANSPARENT, ACCENT_BLUR, ACCENT_ACRYLIC = 0, 2, 3, 4
WCA_ACCENT_POLICY = 19


def _dwm_set(hwnd: int, attr: int, value: int) -> bool:
    import ctypes
    from ctypes import wintypes
    v = ctypes.c_int(value)
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), ctypes.c_uint(attr), ctypes.byref(v),
                                                      ctypes.sizeof(v)) == 0


def _extend_frame(hwnd: int, on: bool):
    import ctypes
    from ctypes import wintypes

    class MARGINS(ctypes.Structure):
        _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]

    # Huge left/right with top/bottom 0 covers the client area without turning the caption strip into
    # DWM glass — that strip is where Windows would otherwise draw its own caption buttons.
    m = MARGINS(16777215, 16777215, 0, 0) if on else MARGINS(0, 0, 0, 0)
    ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(m))


def _blur_behind(hwnd: int, on: bool):
    import ctypes
    from ctypes import wintypes

    class DWM_BLURBEHIND(ctypes.Structure):  # noqa: N801
        _fields_ = [("dwFlags", wintypes.DWORD), ("fEnable", wintypes.BOOL), ("hRgnBlur", wintypes.HRGN),
                    ("fTransitionOnMaximized", wintypes.BOOL)]

    bb = DWM_BLURBEHIND(1, bool(on), None, False)
    ctypes.windll.dwmapi.DwmEnableBlurBehindWindow(wintypes.HWND(hwnd), ctypes.byref(bb))


def _accent(hwnd: int, state: int, abgr: int = 0):
    import ctypes
    from ctypes import wintypes

    class ACCENT_POLICY(ctypes.Structure):  # noqa: N801
        _fields_ = [("AccentState", wintypes.DWORD), ("AccentFlags", wintypes.DWORD),
                    ("GradientColor", wintypes.DWORD), ("AnimationId", wintypes.DWORD)]

    class WINCOMPATTRDATA(ctypes.Structure):
        _fields_ = [("Attribute", wintypes.DWORD), ("Data", ctypes.POINTER(ACCENT_POLICY)),
                    ("SizeOfData", ctypes.c_ulong)]

    policy = ACCENT_POLICY(state, 2 if state == ACCENT_TRANSPARENT else 0, abgr, 0)
    data = WINCOMPATTRDATA(WCA_ACCENT_POLICY, ctypes.pointer(policy), ctypes.sizeof(policy))
    fn = ctypes.windll.user32.SetWindowCompositionAttribute
    fn.argtypes = [wintypes.HWND, ctypes.POINTER(WINCOMPATTRDATA)]
    fn(wintypes.HWND(hwnd), ctypes.byref(data))


def _refresh_frame(hwnd: int):
    """Make Windows recompute and repaint the non-client frame (clears stale caption buttons)."""
    import ctypes
    from ctypes import wintypes
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
    ctypes.windll.user32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0,
                                      SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    RDW_INVALIDATE, RDW_ERASE, RDW_ALLCHILDREN, RDW_UPDATENOW, RDW_FRAME = 0x1, 0x4, 0x80, 0x100, 0x400
    ctypes.windll.user32.RedrawWindow(wintypes.HWND(hwnd), None, None,
                                      RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW | RDW_FRAME)


def apply(window, mode: str) -> str:
    """Apply a backdrop mode to a top-level window. Returns the mode actually in effect."""
    kind = platform_kind()
    if kind == "mac" and mode in MODES:
        try:
            return _mac_apply(window, mode)
        except Exception:  # noqa: BLE001
            return "solid"
    if kind == "other" or mode not in MODES:
        return "solid"
    hwnd = int(window.winId())
    b = windows_build()
    try:
        _dwm_set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
        if kind == "win11":
            _dwm_set(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, 2)
    except Exception:  # noqa: BLE001
        pass

    # start from a clean slate every time
    try:
        if b >= 22621:
            _dwm_set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)
        _accent(hwnd, ACCENT_DISABLED)
    except Exception:  # noqa: BLE001
        pass

    result = "solid"
    try:
        if mode == "solid":
            _blur_behind(hwnd, False)
            _extend_frame(hwnd, False)
        elif mode == "frosted":
            _extend_frame(hwnd, True)
            if b >= 22621 and _dwm_set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_TRANSIENTWINDOW):
                result = "frosted"
            elif kind == "win11" and getattr(window, "windowEffect", None) is not None:
                window.windowEffect.setMicaEffect(hwnd, isDarkMode=True)
                result = "frosted"
            else:
                _blur_behind(hwnd, True)
                _accent(hwnd, ACCENT_BLUR)
                result = "frosted"
        elif mode == "clear":
            _extend_frame(hwnd, True)
            _blur_behind(hwnd, True)  # lets DWM honour the alpha we paint
            _accent(hwnd, ACCENT_TRANSPARENT, 0x00000000)
            result = "clear"
    except Exception:  # noqa: BLE001
        result = "solid"
    try:
        _refresh_frame(hwnd)
    except Exception:  # noqa: BLE001
        pass
    return result


# ---------------------------------------------------------------- variable frost (the QML UI's Frost slider)
def _abgr(rgb: tuple, alpha: int) -> int:
    r, gr, b = rgb
    return (max(0, min(255, int(alpha))) << 24) | (b << 16) | (gr << 8) | r


_FROST_STATE: dict[int, str] = {}  # per window handle (a QML window's Python wrapper can be recreated between calls)


def forget_frost(window) -> None:
    try:
        _FROST_STATE.pop(int(window.winId()), None)
    except Exception:  # noqa: BLE001
        pass


def apply_frost(window, frost: int, rgb: tuple = (16, 16, 18), opacity: float = 1.0) -> str:
    """Glass backdrop whose strength follows `frost` (0..100).

    0 is perfectly clear: the desktop shows through sharp. Above 0 the desktop is blurred (Windows acrylic, whose
    blur radius is fixed by the OS) and the frost percentage sets how strongly it is tinted with the window color;
    that tint also thins out as `opacity` (0.15..1) goes down.
    Returns "clear" or "frosted" (what is actually in effect). Cheap to call repeatedly while a slider is dragged.
    """
    frost = max(0, min(100, int(frost)))
    kind = platform_kind()
    if kind == "mac":
        return _mac_apply(window, "frosted" if frost > 0 else "clear")
    if kind not in ("win10", "win11"):
        return "solid"
    want = "acrylic" if frost > 0 else "clear"
    hwnd = int(window.winId())
    state = _FROST_STATE.get(hwnd)
    try:
        if state != want:
            _FROST_STATE[hwnd] = want
            res = apply(window, "clear")  # clean slate (frame, caption fix, transparent accent)
            if want == "clear":
                return res
            _extend_frame(hwnd, True)
        if want == "clear":
            return "clear"
        # The tint is the frosted-glass layer Windows paints under the app. It fades with the window opacity, so a low
        # opacity really does thin the whole window instead of leaving a dark slab behind the panels.
        fade = max(0.0, min(1.0, (float(opacity) - 0.15) / 0.85))
        _accent(hwnd, ACCENT_ACRYLIC, _abgr(rgb, round(frost / 100 * 0xD0 * fade)))
        return "frosted"
    except Exception:  # noqa: BLE001
        return "clear"
