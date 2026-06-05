"""DashboardView — PySide6. Matplotlib with Qt5Agg backend."""
import hashlib
import json

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from config import COLORS, PRIORITY_COLORS
import data.repository as repo
import i18n

BG       = "#09090b"
CARD_BG  = "#141418"
TEXT     = "#f4f4f5"
TEXT_DIM = "#71717a"
BLUE     = "#60a5fa"
GREEN    = "#4ade80"
GOLD     = "#fbbf24"

PRIORITY_PALETTE = ["#fbbf24","#4ade80","#60a5fa","#52525b"]
GENRE_PALETTE    = [BLUE,GREEN,GOLD,"#f87171","#a78bfa","#22d3ee","#fb923c","#34d399","#e879f9"]
DECADE_PALETTE   = [BLUE,GREEN,GOLD,"#f87171","#a78bfa"]

plt.rcParams.update({
    "text.color": TEXT, "axes.labelcolor": TEXT_DIM,
    "xtick.color": TEXT_DIM, "ytick.color": TEXT_DIM,
    "axes.facecolor": CARD_BG, "figure.facecolor": BG,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False, "axes.spines.bottom": False,
    "axes.grid": False, "font.family": "sans-serif", "font.size": 9,
})


def _lbl(text, size=10, bold=False, color=None):
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold: f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or TEXT}; background-color:transparent;")
    return l


class DashboardView(QFrame):

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
        hb.addWidget(_lbl(i18n.t("dashboard.title"), 16, bold=True))
        hb.addStretch()

        refresh_btn = QPushButton("↻ " + i18n.t("actions.refresh"))
        refresh_btn.setFixedSize(130, 32)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{COLORS['text_dim']};
                border:1px solid {COLORS['border']}; border-radius:6px;
                font-family:'Space Mono'; font-size:12px; }}
            QPushButton:hover {{ background:{COLORS['card_hover']}; }}
        """)
        refresh_btn.clicked.connect(self.refresh)
        hb.addWidget(refresh_btn)
        root.addWidget(header)

        # Scroll
        self._content = QWidget()
        self._content.setStyleSheet(f"background:{BG};")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(16, 16, 16, 16)
        self._content_lay.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._content)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border:none; background:{BG}; }}
            QScrollBar:vertical {{ background:{BG}; width:6px; border:none; }}
            QScrollBar::handle:vertical {{ background:{COLORS['border']}; border-radius:3px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        root.addWidget(scroll, 1)
        self.refresh()

    def refresh(self, force: bool = False):
        games = repo.get_all()
        h = hashlib.md5(json.dumps(
            [(g.id, g.priority, g.price.current if g.price else 0,
              g.price.currency if g.price else "") for g in games]
        ).encode()).hexdigest()
        if not force and h == self._last_hash:
            return
        self._last_hash = h

        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        plt.close("all")

        if not games:
            self._content_lay.addWidget(
                _lbl(i18n.t("dashboard.no_data"), 13, color=COLORS["text_dim"]))
            self._content_lay.addStretch()
            return

        self._render_economic_cards(games)
        self._render_charts(games)
        self._content_lay.addStretch()

    def _render_economic_cards(self, games):
        import data.purchase_repository as purchases
        total     = len(games)
        on_sale   = sum(1 for g in games if g.price and g.price.is_on_sale)
        s_count   = sum(1 for g in games if g.priority == "S")
        total_val = sum(g.price.current for g in games if g.price)
        savings   = sum(g.price.base - g.price.current for g in games
                        if g.price and g.price.is_on_sale and g.price.base > g.price.current)
        currency  = next((g.price.currency for g in games if g.price), "USD")

        total_spent  = purchases.total_spent()
        total_saved  = purchases.total_saved()
        bought_count = len(purchases.get_all())

        row = QWidget()
        row.setStyleSheet("background:transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        cards = [
            (i18n.t("stats.total_games"), str(total),                       BLUE),
            (i18n.t("stats.total_value"), f"${total_val:,.0f} {currency}",   TEXT),
            (i18n.t("stats.savings"),     f"${savings:,.0f} {currency}",    GREEN),
            ("Games bought",              str(bought_count),                  GOLD),
            ("Total spent",               f"${total_spent:,.0f}",            BLUE),
            ("All-time saved",            f"${total_saved:,.0f}",            GREEN),
        ]
        for label, value, color in cards:
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{ background:{CARD_BG};
                    border:1px solid {COLORS['border']}; border-radius:8px; }}
            """)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(2)
            cl.addWidget(_lbl(label, 10, color=TEXT_DIM))
            cl.addWidget(_lbl(value, 18, bold=True, color=color))
            rl.addWidget(card, 1)

        self._content_lay.addWidget(row)

    def _render_charts(self, games):
        row1 = QWidget(); row1.setStyleSheet("background:transparent;")
        r1l  = QHBoxLayout(row1); r1l.setSpacing(8); r1l.setContentsMargins(0,0,0,0)

        row2 = QWidget(); row2.setStyleSheet("background:transparent;")
        r2l  = QHBoxLayout(row2); r2l.setSpacing(8); r2l.setContentsMargins(0,0,0,0)

        row3 = QWidget(); row3.setStyleSheet("background:transparent;")
        r3l  = QHBoxLayout(row3); r3l.setSpacing(8); r3l.setContentsMargins(0,0,0,0)

        self._chart_priority(r1l, games)
        self._chart_bars(r1l, games)
        self._chart_genres(r2l, games)
        self._chart_decades(r2l, games)
        self._chart_spending(r3l)

        for row in (row1, row2, row3):
            self._content_lay.addWidget(row)

    def _make_chart_frame(self, parent_layout, title: str) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{ background:{CARD_BG};
                border:1px solid {COLORS['border']}; border-radius:8px; }}
        """)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(14, 10, 14, 10)
        fl.setSpacing(4)
        fl.addWidget(_lbl(title, 12, bold=True, color=BLUE))
        parent_layout.addWidget(frame, 1)
        return frame

    def _embed_fig(self, parent_layout_widget, fig: Figure):
        frame_lay = parent_layout_widget.layout()
        canvas = FigureCanvasQTAgg(fig)
        canvas.setStyleSheet(f"background:{CARD_BG};")
        frame_lay.addWidget(canvas)
        plt.close(fig)

    def _chart_priority(self, parent_layout, games):
        frame = self._make_chart_frame(parent_layout, i18n.t("dashboard.priorities"))
        counts = {p: sum(1 for g in games if g.priority == p) for p in ("S","A","B","C")}
        labels = [f"{p} ({v})" for p, v in counts.items() if v > 0]
        values = [v for v in counts.values() if v > 0]
        colors = [PRIORITY_PALETTE[i] for i,v in enumerate(counts.values()) if v > 0]
        if not values: return

        fig, ax = plt.subplots(figsize=(3.5, 2.8), facecolor=CARD_BG)
        wedges, texts, autotexts = ax.pie(
            values, labels=None, colors=colors, autopct="%1.0f%%",
            startangle=90, wedgeprops={"linewidth":1.5,"edgecolor":BG}, pctdistance=0.75)
        for at in autotexts:
            at.set_color(BG); at.set_fontsize(9); at.set_fontweight("bold")
        ax.legend(labels, loc="lower center", ncol=4, frameon=False,
                  fontsize=8, labelcolor=TEXT, bbox_to_anchor=(0.5,-0.08))
        fig.tight_layout(pad=0.5)
        self._embed_fig(frame, fig)

    def _chart_bars(self, parent_layout, games):
        frame = self._make_chart_frame(parent_layout, "Prioridad S/A/B/C")
        counts = {p: sum(1 for g in games if g.priority == p) for p in ("S","A","B","C")}

        fig, ax = plt.subplots(figsize=(3.5, 2.8), facecolor=CARD_BG)
        priorities = list(counts.keys()); values = list(counts.values())
        bars = ax.barh(priorities, values, color=PRIORITY_PALETTE, height=0.55, linewidth=0)
        ax.set_xlim(0, max(values)*1.3 if values else 1)
        ax.set_yticks(range(len(priorities)))
        ax.set_yticklabels(priorities, color=TEXT, fontsize=10, fontweight="bold")
        ax.set_xticks([]); ax.tick_params(length=0)
        for bar, val in zip(bars, values):
            ax.text(bar.get_width()+0.1, bar.get_y()+bar.get_height()/2,
                    str(val), va="center", color=TEXT, fontsize=9, fontweight="bold")
        fig.tight_layout(pad=0.5)
        self._embed_fig(frame, fig)

    def _chart_genres(self, parent_layout, games):
        frame = self._make_chart_frame(parent_layout, i18n.t("dashboard.genres"))
        genres: dict[str,int] = {}
        for g in games:
            for genre in g.genre.split(","):
                genre = genre.strip()
                if genre: genres[genre] = genres.get(genre,0)+1
        top = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:8]
        if not top: return

        labels = [t[0] for t in top]; values = [t[1] for t in top]
        fig, ax = plt.subplots(figsize=(5.5, 2.8), facecolor=CARD_BG)
        bars = ax.bar(labels, values, color=GENRE_PALETTE[:len(labels)], width=0.6, linewidth=0)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right", color=TEXT_DIM, fontsize=8)
        ax.set_yticks([]); ax.tick_params(length=0)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.05,
                    str(val), ha="center", va="bottom", color=TEXT, fontsize=8, fontweight="bold")
        fig.tight_layout(pad=0.5)
        self._embed_fig(frame, fig)

    def _chart_decades(self, parent_layout, games):
        frame = self._make_chart_frame(parent_layout, i18n.t("dashboard.decades"))
        decades: dict[str,int] = {}
        for g in games:
            if g.release_year:
                d = f"{(g.release_year//10)*10}s"
                decades[d] = decades.get(d,0)+1
        if not decades: return

        decades = dict(sorted(decades.items()))
        labels = list(decades.keys()); values = list(decades.values())
        fig, ax = plt.subplots(figsize=(5.5, 2.8), facecolor=CARD_BG)
        bars = ax.bar(labels, values, color=DECADE_PALETTE[:len(labels)], width=0.55, linewidth=0)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, color=TEXT_DIM, fontsize=9)
        ax.set_yticks([]); ax.tick_params(length=0)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.05,
                    str(val), ha="center", va="bottom", color=TEXT, fontsize=9, fontweight="bold")
        fig.tight_layout(pad=0.5)
        self._embed_fig(frame, fig)

    def _chart_spending(self, parent_layout):
        import data.purchase_repository as purchases
        all_p = purchases.get_all()
        frame = self._make_chart_frame(
            parent_layout,
            "Purchase History — No purchases yet" if not all_p else "Paid vs. Full Price")

        if not all_p:
            frame.layout().addWidget(_lbl(
                "Click 'I bought this game' on any game detail to track purchases.",
                11, color=TEXT_DIM))
            return

        total_paid  = purchases.total_spent()
        total_base  = purchases.total_base()
        total_saved = purchases.total_saved()
        currency    = all_p[0].currency if all_p else "USD"
        avg_disc    = int(total_saved/total_base*100) if total_base > 0 else 0

        # Summary cards beside chart
        summary_w = QWidget(); summary_w.setStyleSheet("background:transparent;")
        sl = QVBoxLayout(summary_w); sl.setSpacing(6); sl.setContentsMargins(0,0,12,0)
        for label, value, color in [
            ("Total spent",    f"${total_paid:,.0f} {currency}",  BLUE),
            ("Full price was", f"${total_base:,.0f} {currency}",  TEXT_DIM),
            ("Total saved",    f"${total_saved:,.0f} {currency}", GREEN),
            ("Avg. discount",  f"{avg_disc}%",                    GOLD),
            ("Games bought",   str(len(all_p)),                   TEXT),
        ]:
            c = QFrame()
            c.setStyleSheet(f"QFrame {{ background:{CARD_BG}; border:1px solid #27272a; border-radius:6px; }}")
            cl = QVBoxLayout(c); cl.setContentsMargins(10,6,10,6); cl.setSpacing(1)
            cl.addWidget(_lbl(label, 9, color=TEXT_DIM))
            cl.addWidget(_lbl(value, 14, bold=True, color=color))
            sl.addWidget(c)
        sl.addStretch()
        parent_layout.addWidget(summary_w)

        sorted_p = sorted(all_p, key=lambda p: p.purchased_at)
        names    = [p.name[:16]+("…" if len(p.name)>16 else "") for p in sorted_p]
        paid_v   = [p.price_paid  for p in sorted_p]
        base_v   = [p.base_price  for p in sorted_p]
        x        = range(len(names))

        fig, ax = plt.subplots(figsize=(max(4.5, len(names)*0.8), 3.0), facecolor=CARD_BG)
        width = 0.38
        ax.bar([i-width/2 for i in x], base_v, width=width, color="#27272a", label="Full price", linewidth=0)
        bars_paid = ax.bar([i+width/2 for i in x], paid_v, width=width, color=BLUE, label="Paid", linewidth=0)
        for bar, p in zip(bars_paid, sorted_p):
            if p.discount_pct > 0:
                ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.5,
                        f"-{p.discount_pct}%", ha="center", va="bottom",
                        color=GREEN, fontsize=7, fontweight="bold")
        ax.set_xticks(list(x))
        ax.set_xticklabels(names, rotation=30, ha="right", color=TEXT_DIM, fontsize=7)
        ax.set_yticks([]); ax.tick_params(length=0)
        ax.legend(frameon=False, fontsize=8, labelcolor=TEXT, loc="upper right")
        fig.tight_layout(pad=0.5)
        self._embed_fig(frame, fig)