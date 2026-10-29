"""Design tokens, fonts, icons and the app stylesheet."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..core import paths

# ---------------------------------------------------------------- tokens
ACCENT = "#2EE59D"
ON_ACCENT = "#04140C"
TEXT = "#ECF2EE"
TEXT_2 = "#94AA9E"
TEXT_3 = "#72877B"
TEXT_4 = "#506258"
DANGER = "#FF6B6B"
WINDOW_SOLID = "#040806"
PANEL_SOLID = "#08110C"
GLASS_TINT = (2, 10, 6)  # RGB of the glass tint
GLASS_ALPHA = 0.30  # how opaque the tint is over the blur (lower = more see-through)

FONT_UI = "Segoe UI"
FONT_MONO = "Consolas"
FONT_DISPLAY = "Segoe UI"


def keys(seq: str) -> str:
    """Shortcut text for this platform: 'Ctrl+Shift+O' stays on Windows, becomes '⇧⌘O' on a Mac."""
    import sys
    if sys.platform != "darwin":
        return seq
    out = seq.replace("Ctrl+", "⌘").replace("Shift+", "⇧").replace("Alt+", "⌥").replace("Ctrl ", "⌘")
    # macOS writes modifiers in the order ⌥⇧⌘
    mods = "".join(m for m in "⌥⇧⌘" if m in out)
    return mods + "".join(ch for ch in out if ch not in "⌥⇧⌘")


def rgba(hex_color: str, a: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{a:.3f})"


def qcolor(hex_color: str, a: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(a)
    return c


def white(a: float) -> QColor:
    return QColor(255, 255, 255, round(255 * a))


def load_fonts() -> None:
    """Register bundled fonts; fall back to system fonts if missing."""
    global FONT_UI, FONT_MONO, FONT_DISPLAY
    fam = {}
    d = paths.assets_dir() / "fonts"
    for f in sorted(d.glob("*.ttf")):
        if f.stem.startswith("BitGame"):
            continue
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            for name in QFontDatabase.applicationFontFamilies(fid):
                fam.setdefault(f.stem.split("-")[0], name)
    # Inter is the closest freely licensed match to Apple's San Francisco
    FONT_UI = fam.get("Inter", fam.get("Geist", FONT_UI))
    FONT_MONO = fam.get("GeistMono", FONT_MONO)
    FONT_DISPLAY = fam.get("InterDisplay", FONT_UI)


def font(size: float, weight: int = 400, mono: bool = False, display: bool = False) -> QFont:
    f = QFont(FONT_DISPLAY if display else (FONT_MONO if mono else FONT_UI))
    f.setPixelSize(round(size))
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


# ---------------------------------------------------------------- icons (lucide-style strokes)
_ICONS = {
    "link": '<path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.5"/><path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.5-1.5"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12"/>',
    "play": '<path d="M7 4.5v15l12.5-7.5z" fill="{c}" stroke="none"/>',
    "pause": '<rect x="6" y="5" width="4" height="14" rx="1" fill="{c}" stroke="none"/><rect x="14" y="5" width="4" height="14" rx="1" fill="{c}" stroke="none"/>',
    "skip-back": '<path d="M6 5v14"/><path d="M18 5 8 12l10 7z"/>',
    "skip-fwd": '<path d="M18 5v14"/><path d="M6 5l10 7-10 7z"/>',
    "loop": '<path d="M4 12a6 6 0 0 1 6-6h8"/><path d="m15 3 3 3-3 3"/><path d="M20 12a6 6 0 0 1-6 6H6"/><path d="m9 21-3-3 3-3"/>',
    "volume": '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16 9a4 4 0 0 1 0 6"/><path d="M19 6a8 8 0 0 1 0 12"/>',
    "volume-x": '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="m22 9-6 6M16 9l6 6"/>',
    "fullscreen": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "minus": '<path d="M5 12h14"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6"/><path d="M12 16.5v.5"/>',
    "clipboard": '<rect x="8" y="3" width="8" height="4" rx="1"/><path d="M16 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "sliders": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "music": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "repeat": '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "resize": '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    "compress": '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    "film": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 7.5h4M3 12h18M3 16.5h4M17 7.5h4M17 16.5h4"/>',
    "upload": '<path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>',
    "pdf": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/>',
    "rotate-ccw": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "rotate-cw": '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    "flip-h": '<path d="M8 3H5a2 2 0 0 0-2 2v14c0 1.1.9 2 2 2h3"/><path d="M16 3h3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-3"/><path d="M12 20v2M12 14v2M12 8v2M12 2v2"/>',
    "flip-v": '<path d="M21 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v3"/><path d="M21 16v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3"/><path d="M4 12H2M10 12H8M16 12h-2M22 12h-2"/>',
    "unlink": '<path d="m18.84 12.25 1.72-1.71a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="m5.17 11.75-1.71 1.71a5 5 0 0 0 7.07 7.07l1.71-1.71"/><path d="M8 2v3M2 8h3M16 22v-3M22 16h-3"/>',
    "maximize": '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "crop": '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
}


def icon_pixmap(name: str, color: str = TEXT, size: int = 16, stroke: float = 1.8, dpr: float = 2.0) -> QPixmap:
    body = _ICONS[name].replace("{c}", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = TEXT, size: int = 16, stroke: float = 1.8) -> QIcon:
    ic = QIcon()
    ic.addPixmap(icon_pixmap(name, color, size, stroke), QIcon.Normal)
    ic.addPixmap(icon_pixmap(name, TEXT_4, size, stroke), QIcon.Disabled)
    return ic


def app_icon() -> QIcon:
    """Rounded accent square with scissors (window/taskbar icon)."""
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        img = QImage(s, s, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(ACCENT))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.24, s * 0.24)
        sc = icon_pixmap("scissors", ON_ACCENT, s, stroke=2.4, dpr=1.0)
        m = s * 0.18
        p.drawPixmap(QRectF(m, m, s - 2 * m, s - 2 * m).toRect(), sc)
        p.end()
        ic.addPixmap(QPixmap.fromImage(img))
    return ic


# ---------------------------------------------------------------- stylesheet
def qss(mode, opacity: float = 0.45) -> str:
    if mode is True:
        mode = "frosted"
    elif mode is False or mode not in ("frosted", "clear"):
        mode = "solid"
    glass = mode != "solid"
    op = max(0.1, min(1.0, float(opacity)))
    if mode == "clear":  # panels follow the opacity slider so the whole window really thins out
        panel = f"rgba(2,10,6,{0.18 + 0.55 * op:.3f})"
        field_bg = f"rgba(0,6,3,{0.20 + 0.45 * op:.3f})"
        well = f"rgba(0,6,3,{0.16 + 0.42 * op:.3f})"
    elif glass:
        panel = f"rgba(8,30,18,{0.20 + 0.35 * op:.3f})"
        field_bg = f"rgba(0,6,3,{0.18 + 0.30 * op:.3f})"
        well = f"rgba(0,6,3,{0.16 + 0.28 * op:.3f})"
    else:
        panel, field_bg, well = PANEL_SOLID, "#050C08", "#050C08"
    edge = rgba(ACCENT, 0.13) if glass else rgba(ACCENT, 0.09)
    edge_top = rgba(ACCENT, 0.26) if glass else rgba(ACCENT, 0.14)
    hair = rgba(ACCENT, 0.09)
    sel = ACCENT
    return f"""
* {{ font-family: "{FONT_UI}"; color: {TEXT}; outline: none; }}
QWidget {{ font-size: 13px; }}
QToolTip {{ background: #07130D; color: {TEXT}; border: 1px solid rgba(255,255,255,0.12); padding: 5px 8px; border-radius: 6px; }}

#Root {{ background: transparent; }}
#Card {{ background: {panel}; border: 1px solid {edge}; border-top: 1px solid {edge_top}; border-radius: 14px; }}
#Card[busy="true"] {{ border: 1px solid {rgba(ACCENT, 0.35)}; }}
#EmptyCard {{ background: {panel}; border: 1px dashed {rgba(ACCENT, 0.22)}; border-radius: 14px; }}
#Well {{ background: {well}; border: 1px solid {hair}; border-radius: 12px; }}
#Group {{ background: {well}; border: 1px solid {hair}; border-radius: 12px; }}
#GroupSep {{ background: {hair}; max-height: 1px; min-height: 1px; margin-left: 14px; }}
QPushButton#Pill {{ border-radius: 20px; min-height: 40px; font-weight: 500; }}
QPushButton#Disclosure {{ background: transparent; border: none; padding: 0; min-height: 22px; color: {TEXT_2}; font-size: 12px; text-align: left; }}
QPushButton#Disclosure:hover {{ color: {TEXT}; }}
#Divider {{ background: {hair}; max-height: 1px; min-height: 1px; }}
#PlayerFrame {{ background: #000; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }}
#Transport {{ background: rgba(3,10,6,0.96); border-bottom-left-radius: 12px; border-bottom-right-radius: 12px; }}

QLabel {{ background: transparent; }}
QLabel#Muted {{ color: {TEXT_2}; }}
QLabel#Faint {{ color: {TEXT_3}; }}
QLabel#FieldLabel {{ color: {TEXT_2}; font-size: 12px; font-weight: 500; }}
QLabel#Title {{ font-size: 14px; font-weight: 600; }}
QLabel#Big {{ font-size: 22px; font-weight: 600; }}
QLabel#Mono {{ font-family: "{FONT_MONO}"; }}
QLabel#MonoFaint {{ font-family: "{FONT_MONO}"; color: {TEXT_3}; font-size: 11px; }}
QLabel#Badge {{ color: {ACCENT}; background: {rgba(ACCENT, 0.14)}; border-radius: 4px; padding: 1px 6px; font-size: 11px; font-weight: 600; }}
QLabel#Pill {{ background: {rgba(ACCENT, 0.14)}; color: {TEXT_2}; border-radius: 13px; padding: 0 10px; min-height: 26px; max-height: 26px; font-size: 12px; }}
QLabel#Chip {{ font-family: "{FONT_MONO}"; font-size: 11px; color: #C4CEC9; background: rgba(255,255,255,0.05);
              border: 1px solid rgba(255,255,255,0.07); border-radius: 6px; padding: 3px 8px; }}
QLabel#Tag {{ font-size: 11px; font-weight: 500; border-radius: 10px; padding: 2px 8px; color: #C4CEC9; background: rgba(255,255,255,0.07); }}
QLabel#Tag[good="true"] {{ color: {ACCENT}; background: {rgba(ACCENT, 0.14)}; }}
QLabel#ErrorText {{ color: {DANGER}; font-size: 12px; }}

QLineEdit {{ background: {field_bg}; border: 1px solid {hair}; border-radius: 8px;
            padding: 0 10px; min-height: 38px; selection-background-color: {rgba(ACCENT, 0.35)}; font-size: 13px; }}
QLineEdit:focus {{ border: 1px solid {rgba(ACCENT, 0.55)}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {DANGER}; }}
QLineEdit:disabled {{ color: {TEXT_4}; }}
QLineEdit#Bare {{ background: transparent; border: none; min-height: 0; padding: 0; }}
QLineEdit#TimeEdit {{ background: transparent; border: none; min-height: 0; padding: 0; font-family: "{FONT_MONO}"; font-size: 15px; font-weight: 500; }}
QLineEdit#TimeEdit[invalid="true"] {{ color: {DANGER}; }}
#FieldBox {{ background: {field_bg}; border: 1px solid {hair}; border-radius: 8px; }}
#FieldBox[focus="true"] {{ border: 1px solid {rgba(ACCENT, 0.55)}; }}
#FieldBox[invalid="true"] {{ border: 1px solid {DANGER}; }}

QPushButton {{ background: {rgba(ACCENT, 0.05)}; border: 1px solid {rgba(ACCENT, 0.12)}; border-radius: 8px;
              padding: 0 12px; min-height: 34px; color: #DCE5E0; font-weight: 500; }}
QPushButton:hover {{ background: {rgba(ACCENT, 0.11)}; color: #FFFFFF; border: 1px solid {rgba(ACCENT, 0.22)}; }}
QPushButton:pressed {{ background: {rgba(ACCENT, 0.16)}; }}
QPushButton:disabled {{ color: {TEXT_4}; background: rgba(255,255,255,0.03); }}
QPushButton:focus {{ border: 1px solid {rgba(ACCENT, 0.6)}; }}
QPushButton#Primary {{ background: {ACCENT}; color: {ON_ACCENT}; border: none; border-radius: 10px; font-weight: 600; font-size: 14px; }}
QPushButton#Primary:hover {{ background: #4DEDB0; }}
QPushButton#Primary:pressed {{ background: #22C987; }}
QPushButton#Primary:disabled {{ background: rgba(255,255,255,0.08); color: {TEXT_4}; }}
QPushButton#Primary:focus {{ border: 2px solid #B8FFE0; }}
QPushButton#Primary[pill="true"] {{ border-radius: 22px; min-height: 44px; max-height: 44px; }}
QPushButton#Small {{ min-height: 28px; max-height: 28px; padding: 0 9px; font-size: 12px; border-radius: 7px; }}
QPushButton#Small:checked {{ color: {ACCENT}; background: {rgba(ACCENT, 0.14)}; border: 1px solid {rgba(ACCENT, 0.35)}; }}
QPushButton#Link {{ background: transparent; border: none; padding: 0; min-height: 0; color: {ACCENT}; font-size: 12px; }}
QPushButton#Link:hover {{ text-decoration: underline; }}
QPushButton#Icon {{ background: transparent; border: none; border-radius: 8px; padding: 0; min-height: 0; }}
QPushButton#Icon:hover {{ background: {rgba(ACCENT, 0.10)}; }}
QPushButton#Icon:focus {{ border: 1px solid {rgba(ACCENT, 0.6)}; }}
QPushButton#PlayMain {{ background: #FFFFFF; border: none; border-radius: 19px; padding: 0; min-height: 0; }}
QPushButton#PlayMain:hover {{ background: #E6FFF3; }}
QPushButton#Step {{ background: transparent; border: none; border-radius: 0; padding: 0; min-height: 0; }}
QPushButton#Step:hover {{ background: rgba(255,255,255,0.06); }}
QPushButton#BigPlay {{ background: rgba(10,13,12,0.6); border: 1px solid rgba(255,255,255,0.18); border-radius: 32px; padding: 0; }}
QPushButton#BigPlay:hover {{ background: rgba(20,26,23,0.75); }}

#Segmented {{ background: {well}; border: 1px solid {hair}; border-radius: 9px; }}
#Segmented QPushButton {{ background: transparent; border: none; border-radius: 6px; min-height: 30px; max-height: 30px;
                          padding: 0 4px; color: {TEXT_2}; font-size: 12px; font-weight: 500; }}
#Segmented QPushButton:hover {{ color: {TEXT}; }}
#Segmented QPushButton:checked {{ background: {rgba(ACCENT, 0.16)}; color: {ACCENT}; }}
#Segmented QPushButton:disabled {{ color: #3E4844; background: transparent; }}
#Segmented QPushButton:focus {{ border: 1px solid {rgba(ACCENT, 0.5)}; }}
#Segmented[tall="true"] QPushButton {{ min-height: 32px; max-height: 32px; font-size: 13px; }}

QSlider::groove:horizontal {{ height: 4px; background: {rgba(ACCENT, 0.14)}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {sel}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #FFFFFF; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:disabled {{ background: {TEXT_4}; }}
QSlider::sub-page:horizontal:disabled {{ background: {TEXT_4}; }}

QPlainTextEdit#Log {{ background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px;
                     font-family: "{FONT_MONO}"; font-size: 10.5px; color: {TEXT_3}; padding: 6px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {rgba(ACCENT, 0.22)}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QPushButton#TitleTool {{ min-height: 28px; max-height: 28px; border-radius: 14px; padding: 0 11px 0 9px; font-size: 12px;
                        color: #C4CEC9; background: {rgba(ACCENT, 0.05)}; border: 1px solid {rgba(ACCENT, 0.14)}; }}
QPushButton#TitleTool:hover {{ background: {rgba(ACCENT, 0.11)}; color: #FFFFFF; }}
QPushButton#TitleTool:checked {{ color: {ACCENT}; border: 1px solid {rgba(ACCENT, 0.35)}; background: {rgba(ACCENT, 0.12)}; }}
QPushButton#Switcher {{ min-height: 30px; max-height: 30px; border-radius: 15px; padding: 0 14px 0 11px; font-size: 13px;
                        font-weight: 600; color: {TEXT}; background: {rgba(ACCENT, 0.10)}; border: 1px solid {rgba(ACCENT, 0.30)}; }}
QPushButton#Switcher:hover {{ background: {rgba(ACCENT, 0.16)}; }}
QMenu#SessionMenu {{ padding: 6px; border-radius: 12px; }}
QMenu#SessionMenu::item {{ padding: 9px 16px 9px 10px; border-radius: 8px; font-size: 13px; }}
QMenu#SessionMenu::item:checked {{ color: {ACCENT}; background: {rgba(ACCENT, 0.10)}; }}
QMenu#SessionMenu::indicator {{ width: 0; }}
#Popover {{ background: #06100A; border: 1px solid {rgba(ACCENT, 0.22)}; border-radius: 14px; }}
QSpinBox {{ background: {field_bg}; border: 1px solid {hair}; border-radius: 8px; padding: 0 8px;
           min-height: 36px; font-family: "{FONT_MONO}"; }}
QSpinBox:focus {{ border: 1px solid {rgba(ACCENT, 0.55)}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QComboBox {{ background: {field_bg}; border: 1px solid {hair}; border-radius: 8px; padding: 0 10px; min-height: 34px; }}
QComboBox QAbstractItemView {{ background: #07120C; border: 1px solid {rgba(ACCENT, 0.2)}; selection-background-color: {rgba(ACCENT, 0.14)}; }}
#DropZone {{ background: {well}; border: 1.5px dashed {rgba(ACCENT, 0.24)}; border-radius: 14px; }}
#DropZone[hot="true"] {{ border: 1.5px dashed {ACCENT}; background: {rgba(ACCENT, 0.08)}; }}
#DropZone:hover {{ border: 1.5px dashed {rgba(ACCENT, 0.45)}; }}
#QueueRow {{ background: {well}; border: 1px solid {hair}; border-radius: 12px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
#QueueRow[selected="true"] {{ border: 1px solid {rgba(ACCENT, 0.55)}; background: {rgba(ACCENT, 0.07)}; }}
#QueueRow:hover {{ border: 1px solid {rgba(ACCENT, 0.22)}; }}
#EditorBar {{ background: {well}; border: 1px solid {hair}; border-radius: 10px; }}
QPushButton#Chain {{ background: transparent; border: 1px solid transparent; border-radius: 7px; min-height: 0; padding: 0; }}
QPushButton#Chain:checked {{ background: {rgba(ACCENT, 0.14)}; border: 1px solid {rgba(ACCENT, 0.4)}; }}
QPushButton#Chain:hover {{ border: 1px solid {rgba(ACCENT, 0.3)}; }}
QDoubleSpinBox {{ background: {field_bg}; border: 1px solid {hair}; border-radius: 8px; padding: 0 8px;
           min-height: 32px; font-family: "{FONT_MONO}"; }}
QDoubleSpinBox:focus {{ border: 1px solid {rgba(ACCENT, 0.55)}; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {rgba(ACCENT, 0.25)}; }}
QMessageBox {{ background: #08110C; }}
QMessageBox QLabel {{ color: {TEXT}; }}
QMenu {{ background: #07120C; border: 1px solid {rgba(ACCENT, 0.2)}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {rgba(ACCENT, 0.12)}; }}
"""
