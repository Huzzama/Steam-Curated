"""
RecapView — Personal year-in-review stats.
Shows spending, genres, and top games for the current year.
"""
import hashlib
import json
from datetime import datetime

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from config import COLORS, PRIORITY_COLORS
import data.repository as repo
import data.purchase_repository as purchases
import i18n

BG      = "#09090b"
CARD_BG = "#141418"
TEXT    = "#f4f4f5"
DIM     = "#71717a"
BLUE    = "#60a5fa"
GREEN   = "#4ade80"
GOLD    = "#fbbf24"
PINK    = "#f472b6"
PURPLE  = "#a78bfa"


def _lbl(text, size=11, bold=False, color=None, wrap=False):
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold: f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or TEXT}; background-color:transparent;")
    if wrap: l.setWordWrap(True)
    return l


def _card(parent_lay, label, value, color=BLUE, sublabel=None):
    f = QFrame()
    f.setStyleSheet(f"""
        QFrame {{
            background:{CARD_BG};
            border:1px solid #27272a;
            border-left:3px solid {color};
            border-radius:8px;
        }}
    """)
    fl = QVBoxLayout(f)
    fl.setContentsMargins(14, 10, 14, 10)
    fl.setSpacing(2)
    fl.addWidget(_lbl(label, 10, color=DIM))
    fl.addWidget(_lbl(value, 20, bold=True, color=color))
    if sublabel:
        fl.addWidget(_lbl(sublabel, 9, color=DIM))
    parent_lay.addWidget(f, 1)
    return f


class RecapView(QFrame):

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self._last_hash = None
        self.setStyleSheet(f"background:{BG};")
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(52)
        header.setStyleSheet(f"background:{COLORS['panel']}; border:none;")
        hb = QHBoxLayout(header)
        hb.setContentsMargins(18, 0, 18, 0)
        year = datetime.now().year
        hb.addWidget(_lbl(f"{i18n.t('recap.title')}  {year}", 16, bold=True, color=BLUE))
        hb.addWidget(_lbl(i18n.t("recap.this_year", year=year), 11, color=DIM))
        hb.addStretch()
        root.addWidget(header)

        # Scroll
        self._content = QWidget()
        self._content.setStyleSheet(f"background:{BG};")
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(20, 20, 20, 20)
        self._lay.setSpacing(16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._content)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border:none; background:{BG}; }}
            QScrollBar:vertical {{ background:{BG}; width:6px; border:none; }}
            QScrollBar::handle:vertical {{ background:#27272a; border-radius:3px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        root.addWidget(scroll, 1)
        self.refresh()

    def refresh(self):
        year = datetime.now().year
        all_purchases = purchases.get_all()
        year_purchases = [p for p in all_purchases
                          if p.purchased_at.startswith(str(year))]

        h = hashlib.md5(json.dumps(
            [(p.app_id, p.price_paid) for p in year_purchases]
        ).encode()).hexdigest()
        if h == self._last_hash:
            return
        self._last_hash = h

        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        plt.close("all")

        if not year_purchases:
            self._empty_state(year)
            return

        self._render_year_header(year, year_purchases)
        self._render_spending_cards(year, year_purchases)
        self._render_genre_breakdown(year_purchases)
        self._render_top_games(year_purchases)
        self._render_savings_streak(year_purchases)
        self._render_all_time(all_purchases)
        self._lay.addStretch()

    def _empty_state(self, year: int):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        wl = QVBoxLayout(w)
        wl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wl.addWidget(_lbl("🎮", 48))
        wl.addWidget(_lbl(i18n.t("recap.no_data", year=year), 14, color=DIM))
        wl.addWidget(_lbl(
            i18n.t("recap.no_data_hint"),
            11, color=DIM, wrap=True))
        self._lay.addWidget(w)
        self._lay.addStretch()

    # ── Sections ──────────────────────────────────────────────────────────────

    def _render_year_header(self, year: int, yp: list):
        count    = len(yp)
        spent    = sum(p.price_paid for p in yp)
        saved    = sum(p.saved for p in yp)
        currency = yp[0].currency if yp else "USD"

        # Big hero card
        hero = QFrame()
        hero.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #1a1040, stop:1 {CARD_BG});
                border:1px solid {PURPLE}44;
                border-radius:16px;
            }}
        """)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(28, 24, 28, 24)
        hl.setSpacing(6)

        hl.addWidget(_lbl(i18n.t("recap.this_year", year=year), 12, color=DIM))
        hl.addWidget(_lbl(
            i18n.t("recap.bought_count", n=count),
            22, bold=True, color="#fff"))
        hl.addWidget(_lbl(
            i18n.t("recap.saved_msg", amount=f"{saved:,.0f}", currency=currency),
            13, bold=True, color=GREEN))
        self._lay.addWidget(hero)

    def _render_spending_cards(self, year: int, yp: list):
        row = QWidget(); row.setStyleSheet("background:transparent;")
        rl  = QHBoxLayout(row); rl.setSpacing(10); rl.setContentsMargins(0,0,0,0)

        currency   = yp[0].currency if yp else "USD"
        spent      = sum(p.price_paid for p in yp)
        saved      = sum(p.saved      for p in yp)
        base_total = sum(p.base_price for p in yp)
        avg_disc   = int(saved / base_total * 100) if base_total > 0 else 0
        best       = max(yp, key=lambda p: p.saved)

        _card(rl, i18n.t("recap.spent", year=year), f"${spent:,.0f} {currency}", BLUE)
        _card(rl, i18n.t("recap.saved", year=year), f"${saved:,.0f} {currency}", GREEN)
        _card(rl, i18n.t("recap.avg_discount"),    f"{avg_disc}%",               GOLD)
        _card(rl, i18n.t("recap.best_deal"),
              f"-{best.discount_pct}%",
              PINK,
              sublabel=best.name[:20])
        self._lay.addWidget(row)

    def _render_genre_breakdown(self, yp: list):
        # Get genres from wishlist for purchased games
        all_games  = {g.app_id: g for g in repo.get_all()}
        genres: dict[str, int] = {}
        for p in yp:
            g = all_games.get(p.app_id)
            if g and g.genre:
                for genre in g.genre.split(","):
                    genre = genre.strip()
                    if genre:
                        genres[genre] = genres.get(genre, 0) + 1

        if not genres:
            return

        section_lbl = _lbl(i18n.t("recap.genres"), 13, bold=True)
        self._lay.addWidget(section_lbl)

        top = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:6]
        colors = [BLUE, GREEN, GOLD, PINK, PURPLE, "#22d3ee"]

        fig, ax = plt.subplots(figsize=(7, 2.6), facecolor=BG)
        ax.set_facecolor(CARD_BG)
        labels = [t[0] for t in top]
        values = [t[1] for t in top]
        bars = ax.barh(labels[::-1], values[::-1],
                       color=colors[:len(top)][::-1], height=0.55, linewidth=0)
        ax.set_xticks([]); ax.tick_params(length=0)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels[::-1], color=TEXT, fontsize=9)
        for bar, val in zip(bars, values[::-1]):
            ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height()/2,
                    str(val), va="center", color=TEXT, fontsize=9, fontweight="bold")
        fig.tight_layout(pad=0.4)

        canvas = FigureCanvasQTAgg(fig)
        canvas.setStyleSheet(f"background:{BG};")
        self._lay.addWidget(canvas)
        plt.close(fig)

    def _render_top_games(self, yp: list):
        section_lbl = _lbl(i18n.t("recap.games_bought"), 13, bold=True)
        self._lay.addWidget(section_lbl)

        container = QWidget(); container.setStyleSheet("background:transparent;")
        cl = QVBoxLayout(container); cl.setSpacing(6); cl.setContentsMargins(0,0,0,0)

        for p in sorted(yp, key=lambda x: x.purchased_at, reverse=True):
            row = QFrame()
            row.setStyleSheet(f"""
                QFrame {{
                    background:{CARD_BG};
                    border:1px solid #27272a;
                    border-radius:8px;
                }}
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 8, 14, 8)

            name_col = QVBoxLayout()
            name_col.addWidget(_lbl(p.name, 11, bold=True))
            edition_text = p.edition if p.edition and p.edition != "Standard" else ""
            if edition_text:
                name_col.addWidget(_lbl(edition_text, 9, color=GOLD))
            rl.addLayout(name_col, 1)

            price_col = QVBoxLayout()
            price_col.setAlignment(Qt.AlignmentFlag.AlignRight)
            price_col.addWidget(_lbl(f"${p.price_paid:,.0f} {p.currency}",
                                     11, bold=True, color=BLUE))
            if p.saved > 0:
                price_col.addWidget(_lbl(f"saved ${p.saved:,.0f}",
                                         9, color=GREEN))
            rl.addLayout(price_col)

            date_lbl = _lbl(p.purchased_at, 9, color=DIM)
            date_lbl.setFixedWidth(80)
            date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            rl.addWidget(date_lbl)

            cl.addWidget(row)

        self._lay.addWidget(container)

    def _render_savings_streak(self, yp: list):
        """Month-by-month spending chart for the current year."""
        by_month: dict[str, float] = {}
        for p in yp:
            try:
                m = p.purchased_at[:7]  # YYYY-MM
                by_month[m] = by_month.get(m, 0) + p.price_paid
            except Exception:
                pass

        if len(by_month) < 2:
            return

        section_lbl = _lbl(i18n.t("recap.monthly_spending"), 13, bold=True)
        self._lay.addWidget(section_lbl)

        months = sorted(by_month.keys())
        values = [by_month[m] for m in months]
        labels = [m[5:] for m in months]  # MM only

        fig, ax = plt.subplots(figsize=(7, 2.4), facecolor=BG)
        ax.set_facecolor(CARD_BG)
        ax.fill_between(range(len(months)), values,
                        color=BLUE, alpha=0.2, linewidth=0)
        ax.plot(range(len(months)), values,
                color=BLUE, linewidth=2.5, marker="o",
                markersize=6, markerfacecolor=BLUE)
        ax.set_xticks(range(len(months)))
        ax.set_xticklabels(labels, color=DIM, fontsize=9)
        ax.set_yticks([])
        ax.tick_params(length=0)
        ax.spines[:].set_visible(False)

        for i, (val, label) in enumerate(zip(values, labels)):
            ax.text(i, val + max(values)*0.04, f"${val:,.0f}",
                    ha="center", va="bottom",
                    color=TEXT, fontsize=8, fontweight="bold")
        fig.tight_layout(pad=0.4)

        canvas = FigureCanvasQTAgg(fig)
        canvas.setStyleSheet(f"background:{BG};")
        self._lay.addWidget(canvas)
        plt.close(fig)

    def _render_all_time(self, all_purchases: list):
        """All-time summary — shown at the bottom."""
        if not all_purchases:
            return

        self._lay.addWidget(_lbl(i18n.t("recap.all_time"), 13, bold=True))

        total_spent = sum(p.price_paid for p in all_purchases)
        total_saved = sum(p.saved      for p in all_purchases)
        total_count = len(all_purchases)
        currency    = all_purchases[0].currency

        row = QWidget(); row.setStyleSheet("background:transparent;")
        rl  = QHBoxLayout(row); rl.setSpacing(10); rl.setContentsMargins(0,0,0,0)
        _card(rl, i18n.t("recap.total_spent"),  f"${total_spent:,.0f} {currency}", BLUE)
        _card(rl, i18n.t("recap.total_saved"),  f"${total_saved:,.0f} {currency}", GREEN)
        _card(rl, i18n.t("recap.games_count"), str(total_count),                   GOLD)
        _card(rl, i18n.t("recap.avg_per_game"),
              f"${total_spent/total_count:,.0f}" if total_count else "—",
              PURPLE)
        self._lay.addWidget(row)