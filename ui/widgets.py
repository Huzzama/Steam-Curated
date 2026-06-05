"""
Core UI widgets — PySide6.
Drop-in replacements for the old CustomTkinter widgets.
StatCard, SteamButton, SectionHeader, DealBanner.
"""
from __future__ import annotations
from typing import Optional, Callable

from PySide6.QtWidgets import (
    QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QFont, QColor

from config import COLORS, PRIORITY_COLORS


# ── helpers ───────────────────────────────────────────────────────────────────

def _font(size: int = 11, bold: bool = False) -> QFont:
    f = QFont("Space Mono", size)
    if bold:
        f.setBold(True)
    return f


def _qss_color(key: str) -> str:
    return COLORS.get(key, "#888")


# ── StatCard ──────────────────────────────────────────────────────────────────

class StatCard(QFrame):
    """Metric card with colored accent left bar, icon, label and value."""

    def __init__(self, parent=None, label: str = "", value: str = "—",
                 icon: str = "", accent: str = None, **kwargs):
        super().__init__(parent)
        self._accent = accent or COLORS["blue"]
        self._value_lbl: QLabel

        self.setStyleSheet(f"""
            StatCard {{
                background: {COLORS['card']};
                border: 1px solid {COLORS['border']};
                border-left: 3px solid {self._accent};
                border-radius: 8px;
            }}
        """)
        self.setMinimumHeight(72)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 8, 10)
        lay.setSpacing(2)

        # Icon + label row
        top = QHBoxLayout()
        top.setSpacing(4)
        if icon:
            ico = QLabel(icon)
            ico.setFont(_font(12))
            ico.setStyleSheet(f"color: {self._accent};")
            top.addWidget(ico)

        lbl = QLabel(label)
        lbl.setFont(_font(10))
        lbl.setStyleSheet(f"color: {COLORS['text_dim']};")
        top.addWidget(lbl)
        top.addStretch()
        lay.addLayout(top)

        # Value
        self._value_lbl = QLabel(value)
        self._value_lbl.setFont(_font(20, bold=True))
        self._value_lbl.setStyleSheet(f"color: {self._accent};")
        lay.addWidget(self._value_lbl)

    def set_value(self, value: str, color: str = None):
        self._value_lbl.setText(value)
        if color:
            self._value_lbl.setStyleSheet(f"color: {color};")


# ── SteamButton ───────────────────────────────────────────────────────────────

class SteamButton(QPushButton):
    """Styled button — primary / success / ghost variants."""

    _STYLES = {
        "primary": (COLORS["blue"],   "#93c5fd", COLORS["bg"],   COLORS["blue"]),
        "success": (COLORS["green"],  "#86efac", "#000",         COLORS["green"]),
        "ghost":   ("transparent",    COLORS["card_hover"], COLORS["text"], COLORS["border"]),
    }

    def __init__(self, parent=None, text: str = "", command=None,
                 style: str = "primary", **kwargs):
        super().__init__(text, parent)
        if command:
            self.clicked.connect(command)

        bg, hover, fg, border = self._STYLES.get(style, self._STYLES["primary"])
        self.setStyleSheet(f"""
            SteamButton {{
                background: {bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 6px;
                font-family: 'Space Mono';
                font-size: 12px;
                font-weight: bold;
                padding: 4px 14px;
                min-height: 28px;
            }}
            SteamButton:hover {{
                background: {hover};
            }}
            SteamButton:disabled {{
                color: {COLORS['text_dim']};
                border-color: {COLORS['border']};
                background: {COLORS['card']};
            }}
        """)


# ── SectionHeader ─────────────────────────────────────────────────────────────

class SectionHeader(QFrame):
    def __init__(self, parent=None, title: str = "",
                 action_text: str = None, action_cmd=None, **kwargs):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(title)
        lbl.setFont(_font(11, bold=True))
        lbl.setStyleSheet(f"color: {COLORS['text_dim']};")
        lay.addWidget(lbl)
        lay.addStretch()

        if action_text and action_cmd:
            btn = SteamButton(self, text=action_text,
                              command=action_cmd, style="ghost")
            btn.setFixedHeight(26)
            lay.addWidget(btn)


# ── DealBanner ────────────────────────────────────────────────────────────────

class DealBanner(QFrame):
    """Buy-now alert banner."""

    def __init__(self, parent=None, game=None, **kwargs):
        super().__init__(parent)
        self.setStyleSheet(f"""
            DealBanner {{
                background: #0a1f0a;
                border: 1px solid #1a4a1a;
                border-radius: 8px;
            }}
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)

        import i18n
        name = game.name if game else ""
        lbl = QLabel(f"🔥  {name} — {i18n.t('recommendation.buy_now')}")
        lbl.setFont(_font(13, bold=True))
        lbl.setStyleSheet(f"color: {COLORS['green']};")
        lay.addWidget(lbl)

        if game and game.price and game.price_history:
            info = (f"${game.price.current:,.0f} {game.price.currency} · "
                    f"mín: ${game.price_history.all_time_low:,.0f}")
            info_lbl = QLabel(info)
            info_lbl.setFont(_font(11))
            info_lbl.setStyleSheet(f"color: {COLORS['text_dim']};")
            lay.addWidget(info_lbl)

        lay.addStretch()


# ── make_ctk_image (compat shim) ──────────────────────────────────────────────

def make_ctk_image(path: Optional[str], size=(90, 135)):
    """Compat shim — returns QPixmap for PySide6 code."""
    from PySide6.QtGui import QPixmap
    from pathlib import Path
    if path and Path(path).exists():
        px = QPixmap(path)
        return px.scaled(size[0], size[1],
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    # Return blank pixmap
    px = QPixmap(size[0], size[1])
    px.fill(QColor(20, 20, 24))
    return px