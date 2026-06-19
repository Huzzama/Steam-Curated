import hashlib
import json
import threading
from typing import Optional

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from config import COLORS
import data.repository as repo
import data.purchase_repository as purchases
from data.status import STATUS_PURCHASED, normalize_status
import i18n

# ── Colour aliases (all resolved from the single COLORS dict) ─────────────────
# Never define local BG / CARD_BG — always go through COLORS so the whole UI
# shares the same palette and there are no "extra shades of black".
BLUE   = COLORS["blue"]
GREEN  = COLORS["green"]
GOLD   = COLORS["gold"]
PINK   = COLORS.get("pink",   "#f472b6")
PURPLE = COLORS.get("purple", "#a78bfa")
ORANGE = COLORS.get("orange", "#fb923c")
CYAN   = COLORS.get("cyan",   "#22d3ee")
DIM    = COLORS["text_dim"]
TEXT   = COLORS["text"]

PLAY_STATUS_OPTIONS = [
    ("playing",   i18n.t("play_status.playing"),   BLUE),
    ("completed", i18n.t("play_status.completed"), GREEN),
    ("on_hold",   i18n.t("play_status.on_hold"),   GOLD),
    ("abandoned", i18n.t("play_status.abandoned"), PINK),
]
PLAY_STATUS_ICON = {
    "playing":   "▶",
    "completed": "✓",
    "on_hold":   "⏸",
    "abandoned": "✕",
}



# ── Genre translation ─────────────────────────────────────────────────────────
# Steam delivers genre strings in the OS language (e.g. "Acción" on Spanish OS).
# We normalize them to English keys and translate via i18n.
# Unknown genres are shown as-is (untranslated).

_GENRE_NORMALIZE: dict[str, str] = {
    # English
    "action": "action", "adventure": "adventure", "rpg": "rpg",
    "strategy": "strategy", "simulation": "simulation", "sports": "sports",
    "racing": "racing", "puzzle": "puzzle", "horror": "horror",
    "shooter": "shooter", "platformer": "platformer", "fighting": "fighting",
    "stealth": "stealth", "survival": "survival", "indie": "indie",
    "casual": "casual", "mmo": "mmo", "moba": "moba",
    "battle royale": "battle_royale", "sandbox": "sandbox",
    "open world": "open_world", "story rich": "story_rich",
    "visual novel": "visual_novel", "tower defense": "tower_defense",
    "turn-based": "turn_based", "turn based": "turn_based",
    "real-time strategy": "real_time_strategy",
    "real time strategy": "real_time_strategy",
    "first-person": "first_person", "third-person": "third_person",
    "top-down": "top_down", "top down": "top_down",
    "metroidvania": "metroidvania", "roguelike": "roguelike",
    "soulslike": "soulslike", "hack and slash": "hack_and_slash",
    "management": "management", "city builder": "city_builder",
    "exploration": "exploration", "atmospheric": "atmospheric",
    "anime": "anime", "early access": "early_access",
    "free to play": "free_to_play",
    # Spanish (Steam delivers in ES on Spanish OS)
    "acción": "action", "accion": "action",
    "aventura": "adventure", "estrategia": "strategy",
    "simulación": "simulation", "simulacion": "simulation",
    "deportes": "sports", "carreras": "racing",
    "puzle": "puzzle", "terror": "horror",
    "plataformas": "platformer", "lucha": "fighting",
    "sigilo": "stealth", "supervivencia": "survival",
    "mundo abierto": "open_world", "novela visual": "visual_novel",
    "por turnos": "turn_based", "acceso anticipado": "early_access",
    "gratis": "free_to_play",
}


def translate_genre(genre_str: str) -> str:
    """Translate a single genre from Steam to the current i18n locale."""
    if not genre_str:
        return genre_str
    key = _GENRE_NORMALIZE.get(genre_str.lower().strip())
    if key:
        translated = i18n.t(f"genres.{key}")
        if translated and not translated.startswith("genres."):
            return translated
    return genre_str


def translate_genres(genres_str: str, sep: str = ", ") -> str:
    """Translate a comma-separated genres string from Steam."""
    if not genres_str:
        return genres_str
    parts = [translate_genre(g.strip()) for g in genres_str.split(",")]
    return sep.join(p for p in parts if p)


class _Sig(QObject):
    steam_ready = Signal(object)   # dict | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lbl(text: str, size: int = 11, bold: bool = False,
         color: str = None, wrap: bool = False) -> QLabel:
    """
    Label with explicit color + background-color:transparent.
    The transparent background-color declaration is critical: without it a
    QLabel that lives inside a QFrame with a stylesheet can paint an opaque
    rectangle inherited from the parent, causing the 'black box' artefact.
    """
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold:
        f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(
        f"color:{color or TEXT}; background-color:transparent;"
    )
    l.setAutoFillBackground(False)
    if wrap:
        l.setWordWrap(True)
    return l


def _transparent_widget(object_name: str) -> QWidget:
    """QWidget that is explicitly transparent — safe to use as a row wrapper."""
    w = QWidget()
    w.setObjectName(object_name)
    w.setStyleSheet(f"QWidget#{object_name} {{ background: transparent; }}")
    w.setAutoFillBackground(False)
    return w


def _section_header(text: str) -> QWidget:
    """Section separator with label + horizontal rule."""
    w = _transparent_widget("SectionHeader")
    wl = QHBoxLayout(w)
    wl.setContentsMargins(0, 8, 0, 2)
    wl.setSpacing(8)
    wl.addWidget(_lbl(text, 12, bold=True, color=DIM))
    line = QFrame()
    line.setObjectName("SectionLine")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"QFrame#SectionLine {{ color:{COLORS['border']}; }}")
    wl.addWidget(line, 1)
    return w


def _stat_card(lay, label: str, value: str,
               color: str = None, sub: str = None) -> QFrame:
    """
    Bordered stat card.
    Uses QFrame#StatCard_<label_hash> so the selector is always specific and
    never bleeds into child widgets.
    Internal labels inherit background-color:transparent from _lbl().
    """
    color = color or BLUE
    # Unique object name avoids the catch-all QFrame { ... } problem
    uid = abs(hash(label + value)) % 100000
    obj = f"StatCard_{uid}"
    f = QFrame()
    f.setObjectName(obj)
    f.setStyleSheet(f"""
        QFrame#{obj} {{
            background:{COLORS['card']};
            border:1px solid {COLORS['border']};
            border-left:3px solid {color};
            border-radius:8px;
        }}
    """)
    fl = QVBoxLayout(f)
    fl.setContentsMargins(14, 10, 14, 10)
    fl.setSpacing(2)
    fl.addWidget(_lbl(label, 9, color=DIM))
    fl.addWidget(_lbl(value, 18, bold=True, color=color))
    if sub:
        fl.addWidget(_lbl(sub, 8, color=DIM))
    lay.addWidget(f, 1)
    return f


def _embed_chart(parent_layout, fig, center: bool = False,
                 min_height: int = 240) -> FigureCanvasQTAgg:
    """
    Attach a Matplotlib figure to *parent_layout* with all colours unified.

    Rules enforced here:
      • fig.patch  → COLORS["bg"]        (the outer figure background)
      • ax.patch   → COLORS["bg"]        (the axes background)
      • canvas QSS → background-color: COLORS["bg"]
    This means every layer uses the same value, so no colour mismatch appears.

    If the chart lives *inside* a card (COLORS["card"]), call _embed_chart_in_card
    instead which uses COLORS["card"] for all three layers.
    """
    _apply_chart_colors(fig, COLORS["bg"])
    canvas = _make_canvas(fig, COLORS["bg"], min_height)
    if center:
        wrapper = _transparent_widget("ChartWrapper")
        wl = QHBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addStretch()
        wl.addWidget(canvas)
        wl.addStretch()
        parent_layout.addWidget(wrapper)
    else:
        parent_layout.addWidget(canvas)
    plt.close(fig)
    return canvas


def _embed_chart_in_card(card: QFrame, fig,
                          min_height: int = 220) -> FigureCanvasQTAgg:
    """
    Same as _embed_chart but uses COLORS["card"] as the uniform background,
    matching the card that contains it.
    """
    _apply_chart_colors(fig, COLORS["card"])
    canvas = _make_canvas(fig, COLORS["card"], min_height)
    card.layout().addWidget(canvas)
    plt.close(fig)
    return canvas


def _apply_chart_colors(fig, bg_color: str) -> None:
    """Set fig patch, all ax patches, hide spines — all to the same colour."""
    fig.patch.set_facecolor(bg_color)
    fig.patch.set_alpha(1)
    for ax in fig.axes:
        ax.set_facecolor(bg_color)
        ax.patch.set_alpha(1)
        for spine in ax.spines.values():
            spine.set_visible(False)


def _make_canvas(fig, bg_color: str,
                 min_height: int) -> FigureCanvasQTAgg:
    canvas = FigureCanvasQTAgg(fig)
    canvas.setStyleSheet(
        f"background-color:{bg_color}; border:none;"
    )
    canvas.setAutoFillBackground(False)
    canvas.setMinimumHeight(min_height)
    canvas.setSizePolicy(QSizePolicy.Policy.Expanding,
                         QSizePolicy.Policy.Expanding)
    return canvas


# ── Main view ─────────────────────────────────────────────────────────────────

class LibraryView(QFrame):

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self.setObjectName("LibraryView")
        # Use COLORS["bg"] — no local BG constant
        self.setStyleSheet(
            f"QFrame#LibraryView {{ background:{COLORS['bg']}; }}"
        )
        self._last_hash   = None
        self._steam_stats: Optional[dict] = None
        self._sig = _Sig()
        self._sig.steam_ready.connect(self._on_steam_ready)
        self._build_shell()

    # ── Shell (built once) ────────────────────────────────────────────────────

    def _build_shell(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────
        # Use QFrame + QFrame#LibHeader selector (consistent with QFrame type)
        header = QFrame()
        header.setObjectName("LibHeader")
        header.setFixedHeight(52)
        header.setStyleSheet(
            f"QFrame#LibHeader {{ background:{COLORS['panel']}; border:none; }}"
        )
        hb = QHBoxLayout(header)
        hb.setContentsMargins(18, 0, 18, 0)
        hb.addWidget(_lbl("LIBRARY", 16, bold=True, color=BLUE))
        hb.addWidget(_lbl(i18n.t("library.subtitle"), 10, color=DIM))
        hb.addStretch()

        self._refresh_btn = QPushButton(i18n.t("library.refresh"))
        self._refresh_btn.setObjectName("RefreshBtn")
        self._refresh_btn.setFixedSize(100, 30)
        self._refresh_btn.setStyleSheet(f"""
            QPushButton#RefreshBtn {{
                background:transparent; color:{DIM};
                border:1px solid {COLORS['border']}; border-radius:6px;
                font-family:'Space Mono'; font-size:10px;
            }}
            QPushButton#RefreshBtn:hover {{
                background:{COLORS['card_hover']}; color:{TEXT};
            }}
        """)
        self._refresh_btn.clicked.connect(self._force_refresh)
        hb.addWidget(self._refresh_btn)
        root.addWidget(header)

        # ── Scroll area ───────────────────────────────────────────
        self._content = QWidget()
        self._content.setObjectName("LibContent")
        self._content.setStyleSheet(
            f"QWidget#LibContent {{ background:{COLORS['bg']}; }}"
        )
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(20, 20, 20, 20)
        self._lay.setSpacing(20)

        scroll = QScrollArea()
        scroll.setObjectName("LibScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._content)
        scroll.setStyleSheet(f"""
            QScrollArea#LibScroll {{ border:none; background:{COLORS['bg']}; }}
            QScrollBar:vertical {{
                background:{COLORS['bg']}; width:6px; border:none;
            }}
            QScrollBar::handle:vertical {{
                background:{COLORS['border']}; border-radius:3px; min-height:30px;
            }}
            QScrollBar::handle:vertical:hover {{ background:{BLUE}; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        root.addWidget(scroll, 1)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self):
        self._render_all()
        self._fetch_steam_stats()

    def _force_refresh(self):
        from services.library_api import invalidate_cache
        invalidate_cache()
        self._steam_stats = None
        self._last_hash   = None
        self._refresh_btn.setText("…")
        self._refresh_btn.setEnabled(False)
        self._render_all()
        self._fetch_steam_stats()

    def _fetch_steam_stats(self):
        def _work():
            try:
                from services.library_api import get_library_stats
                self._sig.steam_ready.emit(get_library_stats())
            except Exception as e:
                print(f"[LibraryView] {e}")
                self._sig.steam_ready.emit(None)
        threading.Thread(target=_work, daemon=True).start()

    def _on_steam_ready(self, stats):
        self._steam_stats = stats
        self._refresh_btn.setText("↻  Refresh")
        self._refresh_btn.setEnabled(True)
        self._render_all()

    # ── Full render ───────────────────────────────────────────────────────────

    def _render_all(self):
        all_games     = repo.get_all()
        all_purchases = purchases.get_all()

        h = hashlib.md5(json.dumps({
            "games":     len(all_games),
            "purchases": len(all_purchases),
            "steam":     bool(self._steam_stats),
        }).encode()).hexdigest()
        if h == self._last_hash:
            return
        self._last_hash = h

        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        plt.close("all")

        self._lay.addWidget(_section_header(i18n.t("library.section_steam")))
        if self._steam_stats:
            self._render_steam_section(self._steam_stats)
        else:
            self._render_steam_placeholder()

        self._lay.addWidget(_section_header(i18n.t("library.section_curator")))
        self._render_curator_section(all_games, all_purchases)

        self._lay.addWidget(_section_header(i18n.t("library.section_status")))
        self._render_status_section(all_games)

        self._lay.addStretch()

    # ── Section 1: Tu Steam ───────────────────────────────────────────────────

    def _render_steam_placeholder(self):
        from ui.settings_loader import get_settings
        s        = get_settings()
        steam_id = s.get("steam_id64", "").strip()
        has_token= bool(s.get("steamkustom_token", "").strip())

        if steam_id and has_token:
            placeholder = _transparent_widget("LoadingPlaceholder")
            pl = QVBoxLayout(placeholder)
            pl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pl.addWidget(_lbl(i18n.t("library.loading_steam"), 11, color=DIM))
            self._lay.addWidget(placeholder)
        else:
            card = QFrame()
            card.setObjectName("NoCredsCard")
            card.setStyleSheet(f"""
                QFrame#NoCredsCard {{
                    background:{COLORS['card']};
                    border:1px solid {COLORS['border']};
                    border-left:3px solid {GOLD};
                    border-radius:10px;
                }}
            """)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 16, 20, 16)
            cl.setSpacing(6)
            cl.addWidget(_lbl(i18n.t("library.connect_title"), 12,
                               bold=True, color=GOLD))
            cl.addWidget(_lbl(
                i18n.t("library.connect_desc"),
                10, color=DIM, wrap=True))
            self._lay.addWidget(card)

    def _render_steam_section(self, stats: dict):
        # ── Row 1: big numbers ────────────────────────────────────
        row1 = _transparent_widget("SteamRow1")
        r1l = QHBoxLayout(row1)
        r1l.setSpacing(10)
        r1l.setContentsMargins(0, 0, 0, 0)

        never_pct = (int(stats["never_played_count"] /
                         stats["total_games"] * 100)
                     if stats["total_games"] else 0)

        _stat_card(r1l, i18n.t("library.total_games"),  str(stats["total_games"]),         BLUE)
        _stat_card(r1l, i18n.t("library.total_hours"),    f"{stats['total_playtime_hours']:,.0f}h", PURPLE)
        _stat_card(r1l, i18n.t("library.avg_per_game"),   f"{stats['avg_playtime_hours']:.1f}h",   CYAN)
        _stat_card(r1l, i18n.t("library.never_played"),        str(stats["never_played_count"]),   DIM,
                   sub=i18n.t("library.never_pct").format(pct=never_pct))
        self._lay.addWidget(row1)

        # ── Row 2: most/least played ──────────────────────────────
        if stats.get("most_played") or stats.get("least_played"):
            row2 = _transparent_widget("SteamRow2")
            r2l = QHBoxLayout(row2)
            r2l.setSpacing(10)
            r2l.setContentsMargins(0, 0, 0, 0)
            if stats.get("most_played"):
                mp = stats["most_played"]
                _stat_card(r2l, i18n.t("library.most_played"),   f"{mp['hours']:,.0f}h", GREEN, sub=mp["name"][:28])
            if stats.get("least_played"):
                lp = stats["least_played"]
                _stat_card(r2l, i18n.t("library.least_played"), f"{lp['hours']:.1f}h", PINK,  sub=lp["name"][:28])
            self._lay.addWidget(row2)

        # ── Recently played ───────────────────────────────────────
        if stats.get("recently_played"):
            self._lay.addWidget(
                _lbl(i18n.t("library.recently_played"), 10, color=DIM))
            container = _transparent_widget("RecentContainer")
            cl = QVBoxLayout(container)
            cl.setSpacing(5)
            cl.setContentsMargins(0, 0, 0, 0)
            for g in stats["recently_played"]:
                row = QFrame()
                row.setObjectName("RecentRow")
                row.setStyleSheet(f"""
                    QFrame#RecentRow {{
                        background:{COLORS['card']};
                        border:1px solid {COLORS['border']};
                        border-radius:7px;
                    }}
                """)
                rl = QHBoxLayout(row)
                rl.setContentsMargins(12, 7, 12, 7)
                rl.addWidget(_lbl(g["name"], 10, bold=True), 1)
                rl.addWidget(_lbl(i18n.t('library.hours_this_week').format(h=f"{g['hours_2w']:.1f}"), 9, color=BLUE))
                rl.addWidget(_lbl(i18n.t('library.hours_total').format(h=f"{g['hours_total']:,.0f}"),    9, color=DIM))
                cl.addWidget(row)
            self._lay.addWidget(container)

        # ── Top 10 chart ──────────────────────────────────────────
        if stats.get("top_played"):
            self._render_top_played_chart(stats["top_played"])

    def _render_top_played_chart(self, top: list):
        self._lay.addWidget(_lbl(i18n.t("library.top10_chart"), 10, color=DIM))
        names  = [g["name"][:26] for g in top]
        hours  = [g["hours"]     for g in top]
        colors = [BLUE, PURPLE, CYAN, GREEN, GOLD, PINK, ORANGE,
                  "#818cf8", "#34d399", "#fb7185"][:len(top)]

        fig_h = max(4.0, len(top) * 0.7 + 0.8)
        fig, ax = plt.subplots(figsize=(8, fig_h))
        bars = ax.barh(names[::-1], hours[::-1],
                       color=colors[::-1], height=0.55, linewidth=0)
        ax.set_xticks([])
        ax.tick_params(length=0)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names[::-1], color=TEXT, fontsize=10)
        max_h = max(hours) if hours else 1
        for bar, h in zip(bars, hours[::-1]):
            ax.text(bar.get_width() + max_h * 0.01,
                    bar.get_y() + bar.get_height() / 2,
                    f"{h:,.0f}h", va="center", color=TEXT, fontsize=10,
                    fontweight="bold")
        ax.set_xlim(0, max_h * 1.20)
        # Better margins — tight_layout alone can clip rotated labels
        fig.subplots_adjust(left=0.28, right=0.94, top=0.97, bottom=0.05)

        # _embed_chart colours fig + ax + canvas all with COLORS["bg"]
        _embed_chart(self._lay, fig, min_height=int(fig_h * 100))

    # ── Section 2: Steam Curator ──────────────────────────────────────────────

    def _render_curator_section(self, all_games: list, all_purchases: list):
        wishlist = [g for g in all_games if normalize_status(g.status) == "Wishlist"]
        archived = [g for g in all_games if normalize_status(g.status) == "Archivado"]

        # Stats row
        row = _transparent_widget("CuratorRow1")
        rl = QHBoxLayout(row)
        rl.setSpacing(10); rl.setContentsMargins(0, 0, 0, 0)
        _stat_card(rl, i18n.t("library.on_wishlist"),   str(len(wishlist)),       BLUE)
        _stat_card(rl, i18n.t("library.archived"),    str(len(archived)),       DIM)
        _stat_card(rl, i18n.t("library.total_tracked"), str(len(all_games)),      PURPLE)
        _stat_card(rl, i18n.t("library.games_bought"),  str(len(all_purchases)),  GREEN)
        self._lay.addWidget(row)

        if all_purchases:
            total_spent = sum(p.price_paid for p in all_purchases)
            total_saved = sum(p.saved      for p in all_purchases)
            base_total  = sum(p.base_price for p in all_purchases)
            avg_disc    = int(total_saved / base_total * 100) if base_total else 0
            currency    = all_purchases[0].currency

            row2 = _transparent_widget("CuratorRow2")
            r2l = QHBoxLayout(row2)
            r2l.setSpacing(10); r2l.setContentsMargins(0, 0, 0, 0)
            _stat_card(r2l, i18n.t("library.total_spent"),        f"{total_spent:,.0f} {currency}",                GOLD)
            _stat_card(r2l, i18n.t("library.total_saved"),      f"{total_saved:,.0f} {currency}",                GREEN)
            _stat_card(r2l, i18n.t("library.avg_discount"),  f"{avg_disc}%",                                  PINK)
            _stat_card(r2l, i18n.t("library.avg_per_game_spent"),    f"{total_spent/len(all_purchases):,.0f} {currency}", CYAN)
            self._lay.addWidget(row2)

            # ── Purchase list ─────────────────────────────────────────────────
            self._lay.addSpacing(6)
            self._lay.addWidget(_section_header(i18n.t("library.games_bought_title")))

            for i, p in enumerate(sorted(all_purchases,
                                         key=lambda x: x.purchased_at, reverse=True)):
                # Use a stable object name that doesn't embed the index so QSS
                # isn't recomputed for every row on every render.
                row_w = QFrame()
                row_w.setObjectName("PurchaseRow")
                row_w.setStyleSheet(f"""
                    QFrame#PurchaseRow {{
                        background:{COLORS['card']};
                        border:1px solid {COLORS['border']};
                        border-radius:8px;
                    }}
                """)
                rl2 = QHBoxLayout(row_w)
                rl2.setContentsMargins(14, 9, 14, 9)
                rl2.setSpacing(10)

                info_w = _transparent_widget(f"PurchaseInfo_{i}")
                il = QVBoxLayout(info_w); il.setContentsMargins(0,0,0,0); il.setSpacing(2)
                il.addWidget(_lbl(p.name, 12, bold=True))
                if p.edition and p.edition not in ("Standard Edition", "Standard"):
                    il.addWidget(_lbl(p.edition, 10, color=GOLD))
                rl2.addWidget(info_w, 1)

                price_w = _transparent_widget(f"PurchasePrice_{i}")
                pl = QVBoxLayout(price_w); pl.setContentsMargins(0,0,0,0); pl.setSpacing(1)
                pl.setAlignment(Qt.AlignmentFlag.AlignRight)
                pl_lbl = _lbl(f"${p.price_paid:,.0f} {p.currency}", 12, bold=True, color=BLUE)
                pl_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                pl.addWidget(pl_lbl)
                if p.saved > 0:
                    sv = _lbl(f"saved ${p.saved:,.0f} (-{p.discount_pct}%)", 9, color=GREEN)
                    sv.setAlignment(Qt.AlignmentFlag.AlignRight)
                    pl.addWidget(sv)
                rl2.addWidget(price_w)

                date_l = _lbl(p.purchased_at or "", 10, color=DIM)
                date_l.setFixedWidth(85)
                date_l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                rl2.addWidget(date_l)

                self._lay.addWidget(row_w)
                if i < len(all_purchases) - 1:
                    self._lay.addSpacing(4)

        # Wishlist current value
        wishlist_priced = [g for g in wishlist if g.price and g.price.current > 0]
        if wishlist_priced:
            total_wl = sum(g.price.current for g in wishlist_priced)
            currency = wishlist_priced[0].price.currency
            info = QFrame()
            info.setObjectName("WishlistValueCard")
            info.setStyleSheet(f"""
                QFrame#WishlistValueCard {{
                    background:{COLORS['card']};
                    border:1px solid {COLORS['border']};
                    border-left:3px solid {BLUE};
                    border-radius:8px;
                }}
            """)
            il = QHBoxLayout(info)
            il.setContentsMargins(14, 10, 14, 10)
            il.addWidget(_lbl(i18n.t("library.wishlist_value"), 10, color=DIM))
            il.addStretch()
            il.addWidget(_lbl(f"{total_wl:,.0f} {currency}", 14, bold=True, color=BLUE))
            il.addWidget(_lbl(i18n.t("library.wishlist_games_count").format(n=len(wishlist_priced)), 10, color=DIM))
            self._lay.addWidget(info)

    # ── Section 3: Estado ─────────────────────────────────────────────────────

    def _render_status_section(self, all_games: list):
        # normalize_status() catches games whose status was saved as a
        # translated i18n string by an older version of the app (e.g.
        # "Comprado", "Purchased", "Acheté"), so they still show up here
        # instead of silently vanishing because the literal text didn't
        # match "Comprado" exactly.
        comprados = [g for g in all_games if normalize_status(g.status) == STATUS_PURCHASED]
        if not comprados:
            self._lay.addWidget(
                _lbl(i18n.t("library.mark_to_see"), 10, color=DIM))
            return

        counts = {key: 0 for key, *_ in PLAY_STATUS_OPTIONS}
        for g in comprados:
            ps = g.play_status or ""
            if ps in counts:
                counts[ps] += 1

        # Stat pills
        row = _transparent_widget("StatusRow")
        rl = QHBoxLayout(row)
        rl.setSpacing(10)
        rl.setContentsMargins(0, 0, 0, 0)
        for key, label, color in PLAY_STATUS_OPTIONS:
            _stat_card(rl, label, str(counts.get(key, 0)), color)
        self._lay.addWidget(row)

        # Donut chart
        labeled = [(label, counts.get(key, 0), color)
                   for key, label, color in PLAY_STATUS_OPTIONS]
        if sum(c for _, c, _ in labeled) > 0:
            self._render_status_chart(labeled)

        # Per-game status list
        self._lay.addWidget(
            _lbl(i18n.t("library.status_list_title"), 10, color=DIM))
        container = _transparent_widget("StatusList")
        cl = QVBoxLayout(container)
        cl.setSpacing(5)
        cl.setContentsMargins(0, 0, 0, 0)
        for g in sorted(comprados, key=lambda x: x.name):
            self._make_game_status_row(cl, g)
        self._lay.addWidget(container)

    def _render_status_chart(self, labeled: list):
        values = [c   for _, c, _ in labeled if c > 0]
        labels = [lbl for lbl, c, _ in labeled if c > 0]
        colors = [col for _, c, col in labeled if c > 0]
        if not values:
            return

        fig, ax = plt.subplots(figsize=(5, 2.5))
        # NOTE: wedge edgecolor uses COLORS["bg"] so the gap between slices
        # matches the page background — not a hard-coded "#09090b".
        _, texts, autotexts = ax.pie(
            values, labels=labels, colors=colors,
            autopct="%1.0f%%", startangle=90,
            wedgeprops={"linewidth": 2, "edgecolor": COLORS["bg"]},
            textprops={"color": TEXT, "fontsize": 8},
        )
        for at in autotexts:
            at.set_color(COLORS["bg"])
            at.set_fontsize(8)
            at.set_fontweight("bold")
        ax.set_aspect("equal")
        fig.subplots_adjust(left=0.1, right=0.9, top=0.95, bottom=0.05)

        # Centre the donut — _embed_chart colours everything with COLORS["bg"]
        _embed_chart(self._lay, fig, center=True, min_height=260)

    def _make_game_status_row(self, lay, game):
        row = QFrame()
        row.setObjectName("GameStatusRow")
        row.setStyleSheet(f"""
            QFrame#GameStatusRow {{
                background:{COLORS['card']};
                border:1px solid {COLORS['border']};
                border-radius:7px;
            }}
        """)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 6, 12, 6)
        rl.setSpacing(8)
        rl.addWidget(_lbl(game.name, 10, bold=True), 1)

        for key, label, color in PLAY_STATUS_OPTIONS:
            icon   = PLAY_STATUS_ICON.get(key, "")
            active = game.play_status == key
            btn    = QPushButton(f"{icon} {label}")
            btn.setObjectName(f"StatusBtn_{game.id}_{key}")
            btn.setFixedHeight(24)
            btn.setCheckable(True)
            btn.setChecked(active)
            btn.setStyleSheet(self._status_btn_style(color, active))
            btn.clicked.connect(
                lambda _, g=game, k=key, r=row: self._set_play_status(g, k, r))
            rl.addWidget(btn)

        lay.addWidget(row)

    @staticmethod
    def _status_btn_style(color: str, active: bool) -> str:
        bg = "rgba(255,255,255,0.07)" if active else "transparent"
        fg = color if active else DIM
        bd = color if active else COLORS["border"]
        return f"""
            QPushButton {{
                background:{bg}; color:{fg};
                border:1px solid {bd}; border-radius:4px;
                font-family:'Space Mono'; font-size:9px;
                padding:0 7px;
            }}
            QPushButton:hover {{
                background:rgba(255,255,255,0.07);
                color:{color}; border:1px solid {color};
            }}
        """

    def _set_play_status(self, game, key: str, row: QFrame):
        new_status         = "" if game.play_status == key else key
        game.play_status   = new_status
        repo.update(game)
        self._last_hash    = None   # force re-render of chart next time

        # Update button styles in place without rebuilding the row
        rl = row.layout()
        for i in range(rl.count()):
            w = rl.itemAt(i).widget()
            if not isinstance(w, QPushButton):
                continue
            for k, label, color in PLAY_STATUS_OPTIONS:
                icon = PLAY_STATUS_ICON.get(k, "")
                if w.text().strip() == f"{icon} {label}".strip():
                    active = new_status == k
                    w.setChecked(active)
                    w.setStyleSheet(self._status_btn_style(color, active))
                    break