import hashlib
import json
from datetime import datetime

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea, QSizePolicy,
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

# ── Color aliases — single source of truth ───────────────────────────────────
_BG    = COLORS["bg"]
_CARD  = COLORS["card"]
_PANEL = COLORS["panel"]
_BRD   = COLORS["border"]
_TEXT  = COLORS["text"]
_DIM   = COLORS["text_dim"]
_BLUE  = COLORS["blue"]
_GREEN = COLORS.get("green",  "#4ade80")
_GOLD  = COLORS.get("gold",   "#fbbf24")
_PINK  = COLORS.get("pink",   "#f472b6")
_PURP  = COLORS.get("purple", "#a78bfa")


# ── Shared helpers ────────────────────────────────────────────────────────────

def _lbl(text, size=11, bold=False, color=None, wrap=False):
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold:
        f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or _TEXT}; background-color:transparent;")
    l.setAutoFillBackground(False)
    if wrap:
        l.setWordWrap(True)
    return l


def _make_card_frame(name: str, accent_color: str) -> QFrame:
    """Stat card with left accent border."""
    f = QFrame()
    f.setObjectName(name)
    f.setStyleSheet(f"""
        QFrame#{name} {{
            background:{_CARD};
            border:1px solid {_BRD};
            border-left:3px solid {accent_color};
            border-radius:8px;
        }}
    """)
    return f


def _embed_fig(card: QFrame, fig) -> None:
    """
    Embed a Matplotlib figure into a card frame.
    Ensures fig/ax facecolor matches the card background exactly.
    """
    fig.patch.set_facecolor(_CARD)
    fig.patch.set_alpha(1.0)
    for ax in fig.axes:
        ax.set_facecolor(_CARD)
        ax.patch.set_alpha(1.0)
        for spine in ax.spines.values():
            spine.set_visible(False)

    canvas = FigureCanvasQTAgg(fig)
    canvas.setStyleSheet(f"background-color:{_CARD}; border:none;")
    canvas.setAutoFillBackground(False)
    canvas.setMinimumHeight(200)
    canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    card.layout().addWidget(canvas)
    plt.close(fig)


def _chart_card(parent_lay, title: str, accent=None, min_h=260) -> QFrame:
    """Create a chart card frame and add to parent layout."""
    import uuid
    name = "CC_" + uuid.uuid4().hex[:8]
    f = QFrame()
    f.setObjectName(name)
    f.setStyleSheet(f"""
        QFrame#{name} {{
            background:{_CARD};
            border:1px solid {_BRD};
            border-radius:8px;
        }}
    """)
    f.setMinimumHeight(min_h)
    fl = QVBoxLayout(f)
    fl.setContentsMargins(14, 12, 14, 12)
    fl.setSpacing(6)
    if title:
        fl.addWidget(_lbl(title, 11, bold=True, color=accent or _BLUE))
    parent_lay.addWidget(f, 1)
    return f


_card_counter = [0]

def _stat_card(parent_lay, label, value, color=None) -> QFrame:
    color = color or _BLUE
    _card_counter[0] += 1
    f = _make_card_frame(f"StatCard{_card_counter[0]}", color)
    fl = QVBoxLayout(f)
    fl.setContentsMargins(14, 10, 14, 10)
    fl.setSpacing(2)
    fl.addWidget(_lbl(label, 10, color=_DIM))
    fl.addWidget(_lbl(value, 20, bold=True, color=color))
    parent_lay.addWidget(f, 1)
    return f


class RecapView(QFrame):

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self._last_hash = None
        self.setObjectName("RecapView")
        self.setStyleSheet(f"QFrame#RecapView {{ background:{_BG}; }}")
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(52)
        header.setObjectName("RecapHeader")
        header.setStyleSheet(f"""
            QFrame#RecapHeader {{
                background:{_PANEL};
                border:none;
                border-bottom:1px solid {_BRD};
            }}
        """)
        hb = QHBoxLayout(header)
        hb.setContentsMargins(18, 0, 18, 0)
        year = datetime.now().year
        hb.addWidget(_lbl(f"{i18n.t('recap.title')}  {year}", 16, bold=True, color=_BLUE))
        hb.addWidget(_lbl(i18n.t("recap.this_year", year=year), 11, color=_DIM))
        hb.addStretch()
        root.addWidget(header)

        # Scroll content
        self._content = QWidget()
        self._content.setObjectName("RecapContent")
        self._content.setStyleSheet(f"QWidget#RecapContent {{ background:{_BG}; }}")
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(20, 20, 20, 20)
        self._lay.setSpacing(16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._content)
        scroll.setObjectName("RecapScroll")
        scroll.setStyleSheet(f"""
            QScrollArea#RecapScroll {{ border:none; background:{_BG}; }}
            QScrollBar:vertical {{ background:{_BG}; width:6px; border:none; }}
            QScrollBar::handle:vertical {{ background:{_BRD}; border-radius:3px; }}
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

        # Clear synchronously
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w:
                w.hide(); w.setParent(None)
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
        w = QWidget()
        w.setObjectName("RecapEmpty")
        w.setStyleSheet("QWidget#RecapEmpty { background:transparent; }")
        wl = QVBoxLayout(w)
        wl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wl.addWidget(_lbl("🎮", 48))
        wl.addWidget(_lbl(i18n.t("recap.no_data", year=year), 14, color=_DIM))
        wl.addWidget(_lbl(i18n.t("recap.no_data_hint"), 11, color=_DIM, wrap=True))
        self._lay.addWidget(w)
        self._lay.addStretch()

    # ── Sections ──────────────────────────────────────────────────────────────

    def _render_year_header(self, year: int, yp: list):
        count    = len(yp)
        saved    = sum(p.saved for p in yp)
        currency = yp[0].currency if yp else "USD"

        hero = QFrame()
        hero.setObjectName("RecapHero")
        hero.setStyleSheet(f"""
            QFrame#RecapHero {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #1a1040, stop:1 {_CARD});
                border:1px solid {_PURP}44;
                border-radius:16px;
            }}
        """)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(28, 24, 28, 24)
        hl.setSpacing(6)
        hl.addWidget(_lbl(i18n.t("recap.this_year", year=year), 12, color=_DIM))
        hl.addWidget(_lbl(i18n.t("recap.bought_count", n=count), 22, bold=True, color=_TEXT))
        hl.addWidget(_lbl(
            i18n.t("recap.saved_msg", amount=f"{saved:,.0f}", currency=currency),
            13, bold=True, color=_GREEN))
        self._lay.addWidget(hero)

    def _render_spending_cards(self, year: int, yp: list):
        row = QWidget()
        row.setAutoFillBackground(False)
        rl = QHBoxLayout(row)
        rl.setSpacing(10); rl.setContentsMargins(0, 0, 0, 0)

        currency   = yp[0].currency if yp else "USD"
        spent      = sum(p.price_paid for p in yp)
        saved      = sum(p.saved      for p in yp)
        base_total = sum(p.base_price for p in yp)
        avg_disc   = int(saved / base_total * 100) if base_total > 0 else 0
        best       = max(yp, key=lambda p: p.saved)

        _stat_card(rl, i18n.t("recap.spent", year=year), f"${spent:,.0f} {currency}", _BLUE)
        _stat_card(rl, i18n.t("recap.saved", year=year), f"${saved:,.0f} {currency}", _GREEN)
        _stat_card(rl, i18n.t("recap.avg_discount"),     f"{avg_disc}%",               _GOLD)
        _stat_card(rl, i18n.t("recap.best_deal"),
                   f"-{best.discount_pct}%", _PINK)
        self._lay.addWidget(row)

    def _render_genre_breakdown(self, yp: list):
        all_games = {g.app_id: g for g in repo.get_all()}
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

        self._lay.addWidget(_lbl(i18n.t("recap.genres"), 13, bold=True))

        card = _chart_card(self._lay, "", min_h=200)
        top    = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:6]
        colors = [_BLUE, _GREEN, _GOLD, _PINK, _PURP, "#22d3ee"]
        labels = [t[0] for t in top]
        values = [t[1] for t in top]

        fig, ax = plt.subplots(figsize=(7, 2.4))
        bars = ax.barh(labels[::-1], values[::-1],
                       color=colors[:len(top)][::-1], height=0.55, linewidth=0)
        ax.set_xticks([]); ax.tick_params(length=0)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels[::-1], color=_TEXT, fontsize=9)
        for bar, val in zip(bars, values[::-1]):
            ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                    str(val), va="center", color=_TEXT, fontsize=9, fontweight="bold")
        fig.subplots_adjust(left=0.18, right=0.96, top=0.96, bottom=0.08)
        _embed_fig(card, fig)

    def _render_top_games(self, yp: list):
        self._lay.addWidget(_lbl(i18n.t("recap.games_bought"), 13, bold=True))

        container = QWidget()
        container.setAutoFillBackground(False)
        cl = QVBoxLayout(container)
        cl.setSpacing(6); cl.setContentsMargins(0, 0, 0, 0)

        for i, p in enumerate(sorted(yp, key=lambda x: x.purchased_at, reverse=True)):
            rname = f"RecapGame{i}"
            row = QFrame()
            row.setObjectName(rname)
            row.setStyleSheet(f"""
                QFrame#{rname} {{
                    background:{_CARD};
                    border:1px solid {_BRD};
                    border-radius:8px;
                }}
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 8, 14, 8)

            name_col = QVBoxLayout()
            name_col.addWidget(_lbl(p.name, 11, bold=True))
            edition = p.edition if p.edition and p.edition != "Standard" else ""
            if edition:
                name_col.addWidget(_lbl(edition, 9, color=_GOLD))
            rl.addLayout(name_col, 1)

            price_col = QVBoxLayout()
            price_col.setAlignment(Qt.AlignmentFlag.AlignRight)
            price_lbl = _lbl(f"${p.price_paid:,.0f} {p.currency}", 11, bold=True, color=_BLUE)
            price_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            price_col.addWidget(price_lbl)
            if p.saved > 0:
                sv = _lbl(f"saved ${p.saved:,.0f}", 9, color=_GREEN)
                sv.setAlignment(Qt.AlignmentFlag.AlignRight)
                price_col.addWidget(sv)
            rl.addLayout(price_col)

            date_lbl = _lbl(p.purchased_at, 9, color=_DIM)
            date_lbl.setFixedWidth(80)
            date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            rl.addWidget(date_lbl)

            cl.addWidget(row)

        self._lay.addWidget(container)

    def _render_savings_streak(self, yp: list):
        by_month: dict[str, float] = {}
        for p in yp:
            try:
                m = p.purchased_at[:7]
                by_month[m] = by_month.get(m, 0) + p.price_paid
            except Exception:
                pass
        if len(by_month) < 2:
            return

        self._lay.addWidget(_lbl(i18n.t("recap.monthly_spending"), 13, bold=True))

        card   = _chart_card(self._lay, "", min_h=180)
        months = sorted(by_month.keys())
        values = [by_month[m] for m in months]
        labels = [m[5:] for m in months]

        fig, ax = plt.subplots(figsize=(7, 2.2))
        ax.fill_between(range(len(months)), values, color=_BLUE, alpha=0.15, linewidth=0)
        ax.plot(range(len(months)), values, color=_BLUE, linewidth=2.5,
                marker="o", markersize=6, markerfacecolor=_BLUE)
        ax.set_xticks(range(len(months)))
        ax.set_xticklabels(labels, color=_DIM, fontsize=9)
        ax.set_yticks([]); ax.tick_params(length=0)
        ax.spines[:].set_visible(False)
        for i, val in enumerate(values):
            ax.text(i, val + max(values) * 0.05, f"${val:,.0f}",
                    ha="center", va="bottom", color=_TEXT, fontsize=8, fontweight="bold")
        fig.subplots_adjust(left=0.04, right=0.96, top=0.88, bottom=0.18)
        _embed_fig(card, fig)

    def _render_all_time(self, all_purchases: list):
        if not all_purchases:
            return
        self._lay.addWidget(_lbl(i18n.t("recap.all_time"), 13, bold=True))

        total_spent = sum(p.price_paid for p in all_purchases)
        total_saved = sum(p.saved      for p in all_purchases)
        total_count = len(all_purchases)
        currency    = all_purchases[0].currency

        row = QWidget()
        row.setAutoFillBackground(False)
        rl = QHBoxLayout(row)
        rl.setSpacing(10); rl.setContentsMargins(0, 0, 0, 0)
        _stat_card(rl, i18n.t("recap.total_spent"),  f"${total_spent:,.0f} {currency}", _BLUE)
        _stat_card(rl, i18n.t("recap.total_saved"),  f"${total_saved:,.0f} {currency}", _GREEN)
        _stat_card(rl, i18n.t("recap.games_count"),  str(total_count),                  _GOLD)
        _stat_card(rl, i18n.t("recap.avg_per_game"),
                   f"${total_spent/total_count:,.0f}" if total_count else "—", _PURP)
        self._lay.addWidget(row)