from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGraphicsDropShadowEffect,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFont, QDesktopServices, QColor, QPalette

import i18n
from config import COLORS

STEAMDB_URL = "https://steamdb.info/sales/history/all/?live"
SPACING = 12


# ── Helpers ────────────────────────────────────────────────────────────────────

def _label(text: str, size: int = 10, bold: bool = False,
           color: str | None = None, align=Qt.AlignmentFlag.AlignLeft,
           wrap: bool = False) -> QLabel:
    """
    Create a QLabel with correct palette-based coloring.
    Setting the color via QPalette (not stylesheet) means child labels inside
    styled QFrames won't inherit unexpected backgrounds.
    """
    lbl = QLabel(text)
    lbl.setAutoFillBackground(False)

    font = QFont("Space Mono", size)
    if bold:
        font.setBold(True)
    lbl.setFont(font)
    lbl.setAlignment(align)
    if wrap:
        lbl.setWordWrap(True)

    # Use stylesheet only for the foreground color — no background declaration.
    lbl.setStyleSheet(f"color: {color or COLORS['text']};")
    return lbl


def _transparent_widget(layout_type=QVBoxLayout) -> tuple[QWidget, any]:
    """Return a widget that is guaranteed not to paint a background."""
    w = QWidget()
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    w.setAutoFillBackground(False)
    lay = layout_type(w)
    return w, lay


class LinkButton(QPushButton):
    """
    A self-contained quick-link card button.

    Using QPushButton instead of a styled QFrame with child labels solves the
    classic PySide6 hover-not-firing problem: QPushButton tracks mouse enter/
    leave reliably regardless of child widgets, and the stylesheet :hover pseudo-
    class works as expected.
    """

    def __init__(self, emoji: str, label: str, url: str, accent: str,
                 parent=None):
        super().__init__(parent)
        self._url = url
        self.setFixedSize(108, 84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._url)))

        # The button itself is the styled container — no child QFrames needed.
        self.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['card']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                color: {COLORS['text_dim']};
                font-family: 'Space Mono';
                font-size: 8px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {COLORS.get('card_hover', "#ffffff")};
                border-color: {accent};
                color: {COLORS['text']};
            }}
            QPushButton:pressed {{
                background: {COLORS['panel']};
                border-color: {accent};
            }}
        """)

        # Internal layout — labels are purely cosmetic overlays.
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        emoji_lbl = QLabel(emoji)
        emoji_lbl.setFont(QFont("", 20))
        emoji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # setAttribute prevents the label from painting over the button's hover bg.
        emoji_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        emoji_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(emoji_lbl)

        name_lbl = QLabel(label)
        name_lbl.setFont(QFont("Space Mono", 8, QFont.Weight.Bold))
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        name_lbl.setStyleSheet("background: transparent; color: inherit;")
        lay.addWidget(name_lbl)


# ── Main View ──────────────────────────────────────────────────────────────────

class NonSteamFestivalsView(QFrame):

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self.setStyleSheet(f"NonSteamFestivalsView {{ background: {COLORS['bg']}; }}")
        self._build()

    # ── Layout construction ────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        root.addWidget(self._make_content(), stretch=1)

    # ── Header ─────────────────────────────────────────────────────────────────

    def _make_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setFixedHeight(52)
        # Scope the background to this exact widget — children won't inherit it.
        hdr.setObjectName("NonSteamHeader")
        hdr.setStyleSheet(
            f"QWidget#NonSteamHeader {{ background: {COLORS['panel']}; }}"
        )

        hb = QHBoxLayout(hdr)
        hb.setContentsMargins(18, 0, 18, 0)
        hb.setSpacing(10)

        title = QLabel(i18n.t("non_steam.title"))
        title.setFont(QFont("Space Mono", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text']};")
        hb.addWidget(title)

        subtitle = QLabel(i18n.t("non_steam.subtitle"))
        subtitle.setFont(QFont("Space Mono", 9))
        subtitle.setStyleSheet(f"color: {COLORS['text_dim']};")
        hb.addWidget(subtitle)

        hb.addStretch()

        sdb_btn = QPushButton(i18n.t("non_steam.open_steamdb"))
        sdb_btn.setFixedHeight(30)
        sdb_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sdb_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['blue']};
                color: #000000;
                border: none;
                border-radius: 6px;
                font-family: 'Space Mono';
                font-size: 10px;
                font-weight: bold;
                padding: 0 12px;
            }}
            QPushButton:hover  {{ background: #93c5fd; }}
            QPushButton:pressed {{ background: #3b82f6; }}
        """)
        sdb_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(STEAMDB_URL)))
        hb.addWidget(sdb_btn)

        return hdr

    # ── Main content area ──────────────────────────────────────────────────────

    def _make_content(self) -> QWidget:
        content = QWidget()
        content.setObjectName("NonSteamContent")
        # Only target this specific widget — not its children.
        content.setStyleSheet(
            f"QWidget#NonSteamContent {{ background: {COLORS['bg']}; }}"
        )

        cl = QVBoxLayout(content)
        cl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        cl.setSpacing(0)
        cl.setContentsMargins(60, 50, 60, 50)

        cl.addWidget(self._make_hero())
        cl.addSpacing(28)
        cl.addWidget(self._make_links_section())
        cl.addStretch()

        return content

    # ── Hero card ──────────────────────────────────────────────────────────────

    def _make_hero(self) -> QWidget:
        """
        The drop shadow is applied to a transparent *wrapper* widget, not to the
        card QFrame itself.  This keeps the shadow from contaminating the card's
        internal layout and ensures child labels never see an unexpected parent bg.
        """
        wrapper = QWidget()
        wrapper.setAutoFillBackground(False)
        wrapper.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        wrapper.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(48)
        shadow.setColor(QColor(COLORS['blue']).darker(180))
        shadow.setOffset(0, 10)
        wrapper.setGraphicsEffect(shadow)

        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(4, 4, 4, 12)   # room for the shadow
        wl.setSpacing(0)

        # ── Card ──────────────────────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("HeroCard")
        card.setStyleSheet("""
            QFrame#HeroCard {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0d1b2e,
                    stop:1 #111418
                );
                border: 1px solid rgba(96, 165, 250, 0.2);
                border-radius: 16px;
            }
        """)

        hl = QVBoxLayout(card)
        hl.setContentsMargins(48, 40, 48, 40)
        hl.setSpacing(SPACING)
        hl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Badge
        badge = QLabel(i18n.t("non_steam.badge"))
        badge.setFont(QFont("Space Mono", 9, QFont.Weight.Bold))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(120)
        badge.setStyleSheet(f"""
            background: rgba(96, 165, 250, 0.10);
            color: {COLORS['blue']};
            border: 1px solid rgba(96, 165, 250, 0.27);
            border-radius: 4px;
            padding: 4px 12px;
            letter-spacing: 3px;
        """)
        hl.addWidget(badge, alignment=Qt.AlignmentFlag.AlignCenter)

        # Title
        title = QLabel(i18n.t("non_steam.hero_title"))
        title.setFont(QFont("Space Mono", 22, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #f8fafc; background: transparent;")
        hl.addWidget(title)

        # Subtitle — word wrap on, no background declaration needed because the
        # card stylesheet uses an object-name selector (#HeroCard) and does NOT
        # cascade to QLabel children.
        sub = QLabel(i18n.t("non_steam.hero_desc"))
        sub.setFont(QFont("Space Mono", 10))
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent;")
        hl.addWidget(sub)

        hl.addSpacing(8)

        # CTA button
        open_btn = QPushButton(i18n.t("non_steam.hero_btn"))
        open_btn.setFixedHeight(48)
        open_btn.setFont(QFont("Space Mono", 12, QFont.Weight.Bold))
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['blue']};
                color: #000000;
                border: none;
                border-radius: 10px;
                padding: 0 32px;
            }}
            QPushButton:hover   {{ background: #93c5fd; }}
            QPushButton:pressed {{ background: #3b82f6; }}
        """)
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(STEAMDB_URL)))
        hl.addWidget(open_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # URL hint
        url_lbl = QLabel(i18n.t("non_steam.hero_url"))
        url_lbl.setFont(QFont("Space Mono", 8))
        url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        url_lbl.setStyleSheet(
            f"color: {COLORS['border']}; background: transparent;")
        hl.addWidget(url_lbl)

        wl.addWidget(card)
        return wrapper

    # ── Quick links section ────────────────────────────────────────────────────

    def _make_links_section(self) -> QWidget:
        section = QWidget()
        section.setAutoFillBackground(False)
        sl = QVBoxLayout(section)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(10)

        links_title = _label(
            i18n.t("non_steam.quick_links"), 10, bold=True, color=COLORS["text_dim"],
            align=Qt.AlignmentFlag.AlignCenter,
        )
        sl.addWidget(links_title)

        links_row = QHBoxLayout()
        links_row.setSpacing(8)
        links_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        quick_links = [
            ("🔴", i18n.t("non_steam.link_live"),       "https://steamdb.info/sales/history/all/?live", "#e74c3c"),
            ("📅", i18n.t("non_steam.link_calendar"),   "https://steamdb.info/calendar/",               "#3498db"),
            ("📈", i18n.t("non_steam.link_charts"),     "https://steamdb.info/charts/",                 "#2ecc71"),
            ("🏷",  i18n.t("non_steam.link_all_sales"), "https://steamdb.info/sales/history/",          "#f39c12"),
            ("🧮", i18n.t("non_steam.link_calculator"), "https://steamdb.info/calculator/",             "#9b59b6"),
        ]

        for emoji, label, url, accent in quick_links:
            links_row.addWidget(LinkButton(emoji, label, url, accent))

        sl.addLayout(links_row)
        return section

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh(self):
        pass