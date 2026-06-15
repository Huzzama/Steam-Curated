import hashlib
import json

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from config import COLORS, PRIORITY_COLORS
import data.repository as repo
import i18n
from ui.library_view import translate_genre, translate_genres, _GENRE_NORMALIZE

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

PRIORITY_PALETTE = ["#fbbf24", "#4ade80", "#60a5fa", "#52525b"]
GENRE_PALETTE    = [_BLUE, _GREEN, _GOLD, "#f87171", "#a78bfa",
                    "#22d3ee", "#fb923c", "#34d399", "#e879f9"]
DECADE_PALETTE   = [_BLUE, _GREEN, _GOLD, "#f87171", "#a78bfa"]

# Global rcParams — all charts use these as base
plt.rcParams.update({
    "text.color":          _TEXT,
    "axes.labelcolor":     _DIM,
    "xtick.color":         _DIM,
    "ytick.color":         _DIM,
    "axes.facecolor":      _CARD,
    "figure.facecolor":    _CARD,
    "axes.spines.top":     False,
    "axes.spines.right":   False,
    "axes.spines.left":    False,
    "axes.spines.bottom":  False,
    "axes.grid":           False,
    "font.family":         "sans-serif",
    "font.size":           9,
})


# ── Shared helpers ────────────────────────────────────────────────────────────

def _lbl(text, size=10, bold=False, color=None):
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold:
        f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or _TEXT}; background-color:transparent;")
    l.setAutoFillBackground(False)
    return l


def _embed_fig(card: QFrame, fig: Figure) -> None:
    """
    Embed Matplotlib figure into a card.
    Unifies fig/ax/canvas background to the card color.
    """
    card_color = _CARD

    fig.patch.set_facecolor(card_color)
    fig.patch.set_alpha(1.0)
    for ax in fig.axes:
        ax.set_facecolor(card_color)
        ax.patch.set_alpha(1.0)
        for spine in ax.spines.values():
            spine.set_visible(False)

    canvas = FigureCanvasQTAgg(fig)
    canvas.setStyleSheet(f"background-color:{card_color}; border:none;")
    canvas.setAutoFillBackground(False)
    canvas.setMinimumHeight(220)
    canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    card.layout().addWidget(canvas)
    plt.close(fig)


_chart_id = [0]

def _make_chart_frame(parent_layout, title: str, min_h=280) -> QFrame:
    """Create a chart card frame and add it to parent_layout."""
    _chart_id[0] += 1
    name = f"ChartFrame{_chart_id[0]}"
    frame = QFrame()
    frame.setObjectName(name)
    frame.setStyleSheet(f"""
        QFrame#{name} {{
            background:{_CARD};
            border:1px solid {_BRD};
            border-radius:8px;
        }}
    """)
    frame.setMinimumHeight(min_h)
    fl = QVBoxLayout(frame)
    fl.setContentsMargins(16, 14, 16, 14)
    fl.setSpacing(6)
    fl.addWidget(_lbl(title, 12, bold=True, color=_BLUE))
    parent_layout.addWidget(frame, 1)
    return frame


class DashboardView(QFrame):

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self._last_hash = None
        self.setObjectName("DashboardView")
        self.setStyleSheet(f"QFrame#DashboardView {{ background:{_BG}; }}")
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(52)
        header.setObjectName("DashboardHeader")
        header.setStyleSheet(f"""
            QFrame#DashboardHeader {{
                background:{_PANEL};
                border:none;
                border-bottom:1px solid {_BRD};
            }}
        """)
        hb = QHBoxLayout(header)
        hb.setContentsMargins(18, 0, 18, 0)
        hb.addWidget(_lbl(i18n.t("dashboard.title"), 16, bold=True))
        hb.addStretch()

        refresh_btn = QPushButton("↻ " + i18n.t("actions.refresh"))
        refresh_btn.setFixedSize(130, 32)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{_DIM};
                border:1px solid {_BRD}; border-radius:6px;
                font-family:'Space Mono'; font-size:12px;
            }}
            QPushButton:hover {{ background:{COLORS['card_hover']}; }}
        """)
        refresh_btn.clicked.connect(self.refresh)
        hb.addWidget(refresh_btn)
        root.addWidget(header)

        # Scroll content
        self._content = QWidget()
        self._content.setObjectName("DashboardContent")
        self._content.setStyleSheet(
            f"QWidget#DashboardContent {{ background:{_BG}; }}")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(16, 16, 16, 16)
        self._content_lay.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._content)
        scroll.setObjectName("DashboardScroll")
        scroll.setStyleSheet(f"""
            QScrollArea#DashboardScroll {{ border:none; background:{_BG}; }}
            QScrollBar:vertical {{ background:{_BG}; width:6px; border:none; }}
            QScrollBar::handle:vertical {{ background:{_BRD}; border-radius:3px; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        root.addWidget(scroll, 1)
        self.refresh()

    def refresh(self, force: bool = False):
        games = repo.get_all()
        h = hashlib.md5(json.dumps(
            [(g.id, g.priority,
              g.price.current if g.price else 0,
              g.price.currency if g.price else "") for g in games]
        ).encode()).hexdigest()
        if not force and h == self._last_hash:
            return
        self._last_hash = h

        # Clear synchronously
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            w = item.widget()
            if w:
                w.hide(); w.setParent(None)
        plt.close("all")

        if not games:
            self._content_lay.addWidget(
                _lbl(i18n.t("dashboard.no_data"), 13,
                     color=COLORS["text_dim"]))
            self._content_lay.addStretch()
            return

        self._render_economic_cards(games)
        self._content_lay.addSpacing(16)
        self._render_charts(games)
        self._content_lay.addStretch()

    # ── Economic stats ────────────────────────────────────────────────────────

    def _render_economic_cards(self, games):
        import data.purchase_repository as purchases

        on_sale   = sum(1 for g in games if g.price and g.price.is_on_sale)
        total_val = sum(g.price.current for g in games if g.price)
        savings   = sum(
            g.price.base - g.price.current
            for g in games
            if g.price and g.price.is_on_sale and g.price.base > g.price.current
        )
        currency     = next((g.price.currency for g in games if g.price), "USD")
        total_spent  = purchases.total_spent()
        total_saved  = purchases.total_saved()
        bought_count = len(purchases.get_all())

        row = QWidget()
        row.setAutoFillBackground(False)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        stats = [
            (i18n.t("stats.total_games"), str(len(games)),             _BLUE),
            (i18n.t("stats.total_value"), f"${total_val:,.0f} {currency}", _TEXT),
            (i18n.t("stats.savings"),     f"${savings:,.0f} {currency}",   _GREEN),
            (i18n.t("dashboard.games_bought"), str(bought_count),               _GOLD),
            (i18n.t("dashboard.total_spent"),  f"${total_spent:,.0f}",          _BLUE),
            ("All-time saved",            f"${total_saved:,.0f}",          _GREEN),
        ]
        for i, (label, value, color) in enumerate(stats):
            cname = f"EconCard{i}"
            card = QFrame()
            card.setObjectName(cname)
            card.setStyleSheet(f"""
                QFrame#{cname} {{
                    background:{_CARD};
                    border:1px solid {_BRD};
                    border-radius:8px;
                }}
            """)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(2)
            cl.addWidget(_lbl(label, 10, color=_DIM))
            cl.addWidget(_lbl(value, 18, bold=True, color=color))
            rl.addWidget(card, 1)

        self._content_lay.addWidget(row)

    # ── Chart rows ────────────────────────────────────────────────────────────

    def _render_charts(self, games):
        def _row():
            w = QWidget(); w.setAutoFillBackground(False)
            l = QHBoxLayout(w); l.setSpacing(12); l.setContentsMargins(0,0,0,0)
            return w, l

        row1, r1l = _row()
        row2, r2l = _row()
        row3, r3l = _row()

        self._chart_priority(r1l, games)
        self._chart_bars(r1l, games)
        self._chart_genres(r2l, games)
        self._chart_decades(r2l, games)
        self._chart_spending(r3l)

        for row in (row1, row2, row3):
            self._content_lay.addWidget(row)
            self._content_lay.addSpacing(12)

    # ── Individual charts ─────────────────────────────────────────────────────

    def _chart_priority(self, parent_layout, games):
        frame = _make_chart_frame(parent_layout, i18n.t("dashboard.priorities"))
        counts = {p: sum(1 for g in games if g.priority == p)
                  for p in ("S", "A", "B", "C")}
        labels = [f"{p} ({v})" for p, v in counts.items() if v > 0]
        values = [v for v in counts.values() if v > 0]
        colors = [PRIORITY_PALETTE[i]
                  for i, v in enumerate(counts.values()) if v > 0]
        if not values:
            return

        fig, ax = plt.subplots(figsize=(3.5, 2.6))
        wedges, _, autotexts = ax.pie(
            values, labels=None, colors=colors, autopct="%1.0f%%",
            startangle=90,
            wedgeprops={"linewidth": 1.5, "edgecolor": _CARD},
            pctdistance=0.75,
        )
        for at in autotexts:
            at.set_color(_CARD); at.set_fontsize(9); at.set_fontweight("bold")
        ax.legend(labels, loc="lower center", ncol=4, frameon=False,
                  fontsize=8, labelcolor=_TEXT, bbox_to_anchor=(0.5, -0.08))
        fig.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.18)
        _embed_fig(frame, fig)

    def _chart_bars(self, parent_layout, games):
        frame = _make_chart_frame(parent_layout, "Prioridad S/A/B/C")
        counts = {p: sum(1 for g in games if g.priority == p)
                  for p in ("S", "A", "B", "C")}
        priorities = list(counts.keys())
        values     = list(counts.values())

        fig, ax = plt.subplots(figsize=(3.5, 2.6))
        bars = ax.barh(priorities, values,
                       color=PRIORITY_PALETTE, height=0.55, linewidth=0)
        ax.set_xlim(0, max(values) * 1.3 if values else 1)
        ax.set_yticks(range(len(priorities)))
        ax.set_yticklabels(priorities, color=_TEXT, fontsize=10, fontweight="bold")
        ax.set_xticks([]); ax.tick_params(length=0)
        for bar, val in zip(bars, values):
            ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                    str(val), va="center", color=_TEXT,
                    fontsize=9, fontweight="bold")
        fig.subplots_adjust(left=0.12, right=0.94, top=0.96, bottom=0.08)
        _embed_fig(frame, fig)

    def _chart_genres(self, parent_layout, games):
        frame = _make_chart_frame(parent_layout, i18n.t("dashboard.genres"))
        genres: dict[str, int] = {}
        for g in games:
            for genre in g.genre.split(","):
                genre = genre.strip()
                if not genre:
                    continue
                # Normalize to canonical key so "Action"/"Acción" merge
                key = _GENRE_NORMALIZE.get(genre.lower(), genre)
                genres[key] = genres.get(key, 0) + 1
        top_raw = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:8]
        # Translate keys to display labels in current locale
        top = [(i18n.t(f"genres.{k}") if not i18n.t(f"genres.{k}").startswith("genres.") else k, v)
               for k, v in top_raw]
        if not top:
            return

        labels = [t[0] for t in top]
        values = [t[1] for t in top]
        fig, ax = plt.subplots(figsize=(5.5, 2.6))
        bars = ax.bar(labels, values,
                      color=GENRE_PALETTE[:len(labels)], width=0.6, linewidth=0)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right",
                           color=_DIM, fontsize=8)
        ax.set_yticks([]); ax.tick_params(length=0)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.05,
                    str(val), ha="center", va="bottom",
                    color=_TEXT, fontsize=8, fontweight="bold")
        fig.subplots_adjust(left=0.04, right=0.98, top=0.96, bottom=0.32)
        _embed_fig(frame, fig)

    def _chart_decades(self, parent_layout, games):
        frame = _make_chart_frame(parent_layout, i18n.t("dashboard.decades"))
        decades: dict[str, int] = {}
        for g in games:
            if g.release_year:
                d = f"{(g.release_year // 10) * 10}s"
                decades[d] = decades.get(d, 0) + 1
        if not decades:
            return

        decades = dict(sorted(decades.items()))
        labels  = list(decades.keys())
        values  = list(decades.values())
        fig, ax = plt.subplots(figsize=(5.5, 2.6))
        bars = ax.bar(labels, values,
                      color=DECADE_PALETTE[:len(labels)], width=0.55, linewidth=0)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, color=_DIM, fontsize=9)
        ax.set_yticks([]); ax.tick_params(length=0)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.05,
                    str(val), ha="center", va="bottom",
                    color=_TEXT, fontsize=9, fontweight="bold")
        fig.subplots_adjust(left=0.04, right=0.98, top=0.96, bottom=0.18)
        _embed_fig(frame, fig)

    def _chart_spending(self, parent_layout):
        """
        Purchase Summary chart — three aggregate bars only.

        Replaces the old per-game "Paid vs. Full Price" chart which broke down
        every purchase as individual side-by-side bars.  That design fails at
        scale (20+ purchases → unreadable labels, rotated text, visual noise)
        and duplicates data already shown in the summary column.

        New design: always exactly three horizontal bars regardless of how many
        purchases exist:
          ● Full Price  — total_base   (what the collection would cost without deals)
          ● Paid        — total_paid   (money actually spent)
          ● Saved       — total_saved  (money kept thanks to discounts)

        Colors follow the standard traffic-light convention:
          Red   → Full Price  (reference / "what could have been")
          Blue  → Paid        (actual spend)
          Green → Saved       (win)
        """
        import data.purchase_repository as purchases

        all_p = purchases.get_all()
        title = (i18n.t("dashboard.purchase_summary_empty")
                 if not all_p else i18n.t("dashboard.purchase_summary"))
        frame = _make_chart_frame(parent_layout, title, min_h=300)

        if not all_p:
            frame.layout().addWidget(
                _lbl(i18n.t("dashboard.purchase_summary_hint"),
                     11, color=_DIM))
            return

        total_paid  = purchases.total_spent()
        total_base  = purchases.total_base()
        total_saved = purchases.total_saved()
        currency    = all_p[0].currency
        avg_disc    = int(total_saved / total_base * 100) if total_base > 0 else 0

        # ── Inner layout: summary column (left) + chart (right) ───────────────
        inner = QWidget(); inner.setAutoFillBackground(False)
        il = QHBoxLayout(inner)
        il.setSpacing(16); il.setContentsMargins(0, 4, 0, 0)

        # Summary column — identical to before, untouched
        summary = QWidget(); summary.setAutoFillBackground(False)
        sl = QVBoxLayout(summary)
        sl.setSpacing(6); sl.setContentsMargins(0, 0, 0, 0)
        for label, value, color in [
            (i18n.t("dashboard.total_spent"),  f"${total_paid:,.0f} {currency}",  _BLUE),
            (i18n.t("dashboard.full_price_was"), f"${total_base:,.0f} {currency}",  _DIM),
            (i18n.t("dashboard.total_saved"),  f"${total_saved:,.0f} {currency}", _GREEN),
            (i18n.t("dashboard.avg_discount"), f"{avg_disc}%",                    _GOLD),
            (i18n.t("dashboard.games_bought"), str(len(all_p)),                   _TEXT),
        ]:
            sl.addWidget(_lbl(label, 9, color=_DIM))
            sl.addWidget(_lbl(value, 14, bold=True, color=color))
            sl.addSpacing(4)
        sl.addStretch()
        il.addWidget(summary, 0)

        # ── Aggregate bar chart — always 3 bars, no per-game breakdown ────────
        # The canvas must live inside `inner` as the right column so that
        # summary (left, fixed width) and chart (right, expanding) sit side by
        # side in the HBoxLayout.  _embed_fig() adds to card.layout() which is
        # the frame's VBoxLayout — we DON'T use it here.  Instead we build the
        # canvas manually and add it to `il` (the inner HBoxLayout).
        _RED = "#f87171"   # full price — reference cost

        labels = [i18n.t("dashboard.bar_full_price"), i18n.t("dashboard.bar_paid"), i18n.t("dashboard.bar_saved")]
        values = [total_base,   total_paid,   total_saved]
        colors = [_RED,         _BLUE,        _GREEN]
        max_v  = max(values) if any(v > 0 for v in values) else 1

        fig, ax = plt.subplots(figsize=(5.5, 2.0))

        # Unify figure/axes background with the card — same logic as _embed_fig
        fig.patch.set_facecolor(_CARD); fig.patch.set_alpha(1.0)
        ax.set_facecolor(_CARD);        ax.patch.set_alpha(1.0)
        for spine in ax.spines.values():
            spine.set_visible(False)

        bars = ax.barh(labels, values, color=colors, height=0.52, linewidth=0)

        # Value labels at the right end of each bar
        for bar, val in zip(bars, values):
            ax.text(
                bar.get_width() + max_v * 0.02,
                bar.get_y() + bar.get_height() / 2,
                f"${val:,.0f} {currency}",
                va="center", ha="left",
                color=_TEXT, fontsize=9, fontweight="bold",
            )

        ax.set_xlim(0, max_v * 1.35)
        ax.set_xticks([])
        ax.tick_params(length=0)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, color=_TEXT, fontsize=10, fontweight="bold")
        fig.subplots_adjust(left=0.20, right=0.98, top=0.96, bottom=0.08)

        # Build canvas and add directly to the inner HBoxLayout (right column)
        canvas = FigureCanvasQTAgg(fig)
        canvas.setStyleSheet(f"background-color:{_CARD}; border:none;")
        canvas.setAutoFillBackground(False)
        canvas.setMinimumHeight(160)
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Expanding)
        plt.close(fig)

        il.addWidget(canvas, 1)          # stretch=1 → canvas takes remaining space

        # Now add the completed inner widget (summary left + canvas right) to frame
        frame.layout().addWidget(inner)