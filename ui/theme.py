"""
Design tokens + the application stylesheet — the single source of truth for
how Steam Curator looks. Mirrors the PimpMySteam web tokens
(--bg/--surface/--border/--text/--accent…) so desktop and web read as one
brand.

Rules for every view:
  * colours only via C[...]                (no hex in views)
  * type only via font(...) / the QSS classes
  * spacing from SP, radii from R
  * icons via ui.icons (never emoji / unicode glyphs)
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QPalette, QColor

# ── Colour tokens ──────────────────────────────────────────────────────────────
C = {
    # surfaces (cold near-black, same ramp as the web)
    "bg":            "#09090b",
    "surface":       "#0f0f12",
    "surface_2":     "#141418",
    "surface_3":     "#1a1a20",
    "hover":         "#1c1c22",
    "border":        "#1f1f26",
    "border_strong": "#2a2a33",
    # text (all ≥ 4.5:1 on bg)
    "text":          "#f4f4f5",
    "text_2":        "#c4c4cc",
    "text_dim":      "#8b8b96",
    "text_muted":    "#5e5e6a",
    # brand
    "accent":        "#60a5fa",
    "accent_soft":   "#1d4ed8",
    "accent_dim":    "#12233f",
    "on_accent":     "#06101c",
    # semantic / data
    "green":         "#4ade80",
    "green_dim":     "#0f2a1a",
    "gold":          "#fbbf24",
    "gold_dim":      "#2b2109",
    "red":           "#f87171",
    "red_dim":       "#2c1212",
    "pink":          "#f472b6",
    "violet":        "#a78bfa",
    "cyan":          "#22d3ee",
    "orange":        "#fb923c",
}

PRIORITY = {"S": C["gold"], "A": C["green"], "B": C["accent"], "C": C["text_dim"]}
PRIORITY_DIM = {"S": C["gold_dim"], "A": C["green_dim"], "B": C["accent_dim"], "C": C["surface_3"]}

# ── Spacing / radii / motion ───────────────────────────────────────────────────
SP = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32, "3xl": 48}
R  = {"sm": 6, "md": 10, "lg": 14, "xl": 20, "pill": 14}
DURATION = {"fast": 120, "base": 200, "slow": 320}

# ── Type ───────────────────────────────────────────────────────────────────────
FONT_SANS    = "Inter"
FONT_MONO    = "Space Mono"
FONT_DISPLAY = "Bebas Neue"
_FALLBACK_SANS = "Segoe UI"
_FALLBACK_MONO = "Consolas"

# point sizes — one scale, nothing outside it
FS = {"2xs": 9, "xs": 10, "sm": 11, "base": 12, "md": 13, "lg": 15, "xl": 18,
      "2xl": 24, "3xl": 34, "hero": 48}

_fonts_loaded = False
_families: set[str] = set()


def load_fonts() -> None:
    """Register the bundled OFL fonts once (Inter, Space Mono, Bebas Neue)."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    _fonts_loaded = True
    from config import BUNDLE_DIR
    folder = Path(BUNDLE_DIR) / "assets" / "fonts"
    if not folder.exists():
        return
    for f in sorted(folder.glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            _families.update(QFontDatabase.applicationFontFamilies(fid))


def sans() -> str:
    return FONT_SANS if FONT_SANS in _families else _FALLBACK_SANS


def mono() -> str:
    return FONT_MONO if FONT_MONO in _families else _FALLBACK_MONO


def display() -> str:
    return FONT_DISPLAY if FONT_DISPLAY in _families else sans()


def font(size: str = "base", weight: int = QFont.Weight.Normal, family: str = "sans",
         letter_spacing: float = 0.0) -> QFont:
    fam = {"sans": sans(), "mono": mono(), "display": display()}[family]
    f = QFont(fam, FS[size])
    if not isinstance(weight, QFont.Weight):
        weight = QFont.Weight(int(weight))
    f.setWeight(weight)
    if letter_spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    return f


# ── Global stylesheet ──────────────────────────────────────────────────────────

_chevron_file: str = ""


def _chevron_path() -> str:
    """Write a tinted chevron SVG once (QSS `image:` needs a file URL)."""
    global _chevron_file
    if not _chevron_file:
        import tempfile
        from pathlib import Path as _P
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" '
               f'stroke="{C["text_dim"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               f'<path d="m6 9 6 6 6-6"/></svg>')
        f = _P(tempfile.gettempdir()) / "steamcurator_chevron.svg"
        try:
            f.write_text(svg, encoding="utf-8")
            _chevron_file = f.as_posix()
        except OSError:
            _chevron_file = ""
    return _chevron_file


def _px(pt: int) -> int:
    """QSS wants px; keep the visual size of the pt scale at 96 dpi."""
    return round(pt * 96 / 72)


def stylesheet() -> str:
    c, s = C, sans()
    m = mono()
    return f"""
    * {{ font-family: '{s}'; font-size: {_px(FS['base'])}px; color: {c['text']}; }}
    QWidget {{ background: transparent; }}
    QMainWindow, QDialog {{ background: {c['bg']}; }}
    QToolTip {{ background: {c['surface_3']}; color: {c['text']}; border: 1px solid {c['border_strong']};
                padding: 6px 8px; border-radius: {R['sm']}px; }}

    /* ── text roles (set objectName / property) ─────────────────────────── */
    QLabel[role="title"]    {{ font-size: {_px(FS['xl'])}px; font-weight: 600; letter-spacing: -0.3px; color: {c['text']}; }}
    QLabel[role="h2"]       {{ font-size: {_px(FS['lg'])}px; font-weight: 600; color: {c['text']}; }}
    QLabel[role="body"]     {{ color: {c['text_2']}; }}
    QLabel[role="dim"]      {{ color: {c['text_dim']}; }}
    QLabel[role="muted"]    {{ color: {c['text_muted']}; font-size: {_px(FS['sm'])}px; }}
    QLabel[role="eyebrow"]  {{ font-family: '{m}'; font-size: {_px(FS['2xs'])}px; color: {c['text_dim']};
                               letter-spacing: 2px; text-transform: uppercase; }}
    QLabel[role="mono"]     {{ font-family: '{m}'; }}
    QLabel[role="value"]    {{ font-family: '{m}'; font-size: {_px(FS['2xl'])}px; font-weight: 700; letter-spacing: -0.5px; }}

    /* ── surfaces ───────────────────────────────────────────────────────── */
    QFrame[surface="card"]      {{ background: {c['surface_2']}; border: 1px solid {c['border']}; border-radius: {R['lg']}px; }}
    QFrame[surface="card"]:hover[hoverable="true"] {{ background: {c['hover']}; border-color: {c['border_strong']}; }}
    QFrame[surface="card"][active="true"] {{ background: {c['accent_dim']}; border-color: {c['accent_soft']}; }}
    QFrame[surface="panel"]     {{ background: {c['surface']}; border: none; }}
    QFrame[surface="inset"]     {{ background: {c['bg']}; border: 1px solid {c['border']}; border-radius: {R['md']}px; }}
    QFrame[surface="divider"]   {{ background: {c['border']}; max-height: 1px; min-height: 1px; border: none; }}
    QFrame[surface="sidebar"]   {{ background: {c['surface']}; border-right: 1px solid {c['border']}; }}

    /* ── buttons ────────────────────────────────────────────────────────── */
    QPushButton {{
        background: {c['surface_3']}; color: {c['text']}; border: 1px solid {c['border_strong']};
        border-radius: {R['md']}px; padding: 7px 14px; font-weight: 500; min-height: 18px;
    }}
    QPushButton:hover    {{ background: {c['hover']}; border-color: {c['text_muted']}; }}
    QPushButton:pressed  {{ background: {c['surface_2']}; }}
    QPushButton:disabled {{ color: {c['text_muted']}; border-color: {c['border']}; background: {c['surface_2']}; }}
    QPushButton:focus    {{ border-color: {c['accent']}; }}

    QPushButton[variant="primary"] {{ background: {c['accent']}; color: {c['on_accent']}; border: 1px solid {c['accent']}; font-weight: 600; }}
    QPushButton[variant="primary"]:hover   {{ background: #7ab5fb; border-color: #7ab5fb; }}
    QPushButton[variant="primary"]:pressed {{ background: #4d93ea; }}
    QPushButton[variant="primary"]:disabled {{ background: {c['accent_dim']}; color: {c['text_muted']}; border-color: {c['accent_dim']}; }}

    QPushButton[variant="success"] {{ background: {c['green']}; color: {c['on_accent']}; border: 1px solid {c['green']}; font-weight: 600; }}
    QPushButton[variant="success"]:hover {{ background: #6ee79a; }}
    QPushButton[variant="danger"]  {{ background: transparent; color: {c['red']}; border: 1px solid {c['red_dim']}; }}
    QPushButton[variant="danger"]:hover {{ background: {c['red_dim']}; }}
    QPushButton[variant="ghost"]   {{ background: transparent; border: 1px solid transparent; color: {c['text_2']}; }}
    QPushButton[variant="ghost"]:hover {{ background: {c['surface_3']}; color: {c['text']}; }}
    QPushButton[variant="link"]    {{ background: transparent; border: none; color: {c['accent']}; padding: 2px 4px; }}
    QPushButton[variant="link"]:hover {{ color: #93c5fd; }}

    QPushButton[variant="icon"] {{ background: transparent; border: 1px solid transparent; padding: 6px; min-width: 18px; border-radius: {R['md']}px; }}
    QPushButton[variant="icon"]:hover {{ background: {c['surface_3']}; }}
    QPushButton[variant="icon"]:checked {{ background: {c['accent_dim']}; border-color: {c['accent_soft']}; }}

    /* sidebar nav item */
    QPushButton[variant="nav"] {{ background: transparent; border: 1px solid transparent; border-radius: {R['md']}px;
                                  color: {c['text_dim']}; text-align: left; padding: 8px 12px; font-weight: 500; }}
    QPushButton[variant="nav"]:hover {{ background: {c['surface_3']}; color: {c['text']}; }}
    QPushButton[variant="nav"][active="true"] {{ background: {c['accent_dim']}; color: {c['text']}; border-color: {c['border']}; }}

    /* chips / segmented control */
    QPushButton[variant="chip"] {{ background: transparent; border: 1px solid {c['border_strong']}; border-radius: {R['pill']}px;
                                   color: {c['text_dim']}; padding: 4px 12px; font-size: {_px(FS['sm'])}px; font-weight: 500; }}
    QPushButton[variant="chip"]:hover {{ color: {c['text']}; border-color: {c['text_muted']}; }}
    QPushButton[variant="chip"][active="true"] {{ background: {c['text']}; color: {c['bg']}; border-color: {c['text']}; }}
    QPushButton[variant="seg"] {{ background: transparent; border: none; border-radius: {R['sm']}px; color: {c['text_dim']};
                                  padding: 5px 12px; font-size: {_px(FS['sm'])}px; font-weight: 500; }}
    QPushButton[variant="seg"][active="true"] {{ background: {c['surface_3']}; color: {c['text']}; }}
    QFrame[surface="seg"] {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {R['md']}px; }}

    /* ── inputs ─────────────────────────────────────────────────────────── */
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
        background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border_strong']};
        border-radius: {R['md']}px; padding: 7px 10px; selection-background-color: {c['accent_soft']};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
        border-color: {c['accent']};
    }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {c['text_muted']}; }}
    QLineEdit[error="true"] {{ border-color: {c['red']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url({_chevron_path()}); width: 14px; height: 14px; }}
    QComboBox QAbstractItemView {{ background: {c['surface_3']}; color: {c['text']}; border: 1px solid {c['border_strong']};
                                   selection-background-color: {c['accent_dim']}; outline: 0; padding: 4px; }}
    QCheckBox {{ spacing: 8px; color: {c['text_2']}; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {c['border_strong']}; background: {c['surface']}; }}
    QCheckBox::indicator:hover {{ border-color: {c['text_muted']}; }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

    /* ── progress ───────────────────────────────────────────────────────── */
    QProgressBar {{ background: {c['surface_3']}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
    QProgressBar[tone="gold"]::chunk  {{ background: {c['gold']}; }}
    QProgressBar[tone="green"]::chunk {{ background: {c['green']}; }}

    /* ── scrollbars ─────────────────────────────────────────────────────── */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['border_strong']}; border-radius: 3px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['text_muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c['border_strong']}; border-radius: 3px; min-width: 28px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

    QSplitter::handle {{ background: {c['border']}; width: 1px; }}
    QMenu {{ background: {c['surface_3']}; border: 1px solid {c['border_strong']}; border-radius: {R['md']}px; padding: 6px; }}
    QMenu::item {{ padding: 6px 14px; border-radius: {R['sm']}px; }}
    QMenu::item:selected {{ background: {c['accent_dim']}; }}
    """


def palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor(C["bg"]))
    p.setColor(QPalette.ColorRole.WindowText,      QColor(C["text"]))
    p.setColor(QPalette.ColorRole.Base,            QColor(C["surface"]))
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor(C["surface_2"]))
    p.setColor(QPalette.ColorRole.Text,            QColor(C["text"]))
    p.setColor(QPalette.ColorRole.Button,          QColor(C["surface_3"]))
    p.setColor(QPalette.ColorRole.ButtonText,      QColor(C["text"]))
    p.setColor(QPalette.ColorRole.Highlight,       QColor(C["accent"]))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(C["on_accent"]))
    p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(C["surface_3"]))
    p.setColor(QPalette.ColorRole.ToolTipText,     QColor(C["text"]))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(C["text_muted"]))
    return p


def apply(app) -> None:
    """Call once after QApplication is created."""
    load_fonts()
    app.setStyle("Fusion")
    app.setPalette(palette())
    app.setFont(font("base"))
    app.setStyleSheet(stylesheet())


def repolish(widget) -> None:
    """Re-evaluate QSS after a dynamic property (active/variant/…) changed."""
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()
