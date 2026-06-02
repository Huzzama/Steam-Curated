import customtkinter as ctk
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from config import COLORS, PRIORITY_COLORS
import data.repository as repo
import i18n

BG = "#09090b"
CARD_BG = "#141418"
TEXT = "#f4f4f5"
TEXT_DIM = "#71717a"
BLUE = "#60a5fa"
GREEN = "#4ade80"
GOLD = "#fbbf24"

PRIORITY_PALETTE = ["#fbbf24", "#4ade80", "#60a5fa", "#52525b"]
GENRE_PALETTE = [BLUE, GREEN, GOLD, "#f87171", "#a78bfa",
                 "#22d3ee", "#fb923c", "#34d399", "#e879f9"]
DECADE_PALETTE = [BLUE, GREEN, GOLD, "#f87171", "#a78bfa"]

plt.rcParams.update({
    "text.color": TEXT,
    "axes.labelcolor": TEXT_DIM,
    "xtick.color": TEXT_DIM,
    "ytick.color": TEXT_DIM,
    "axes.facecolor": CARD_BG,
    "figure.facecolor": BG,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "axes.spines.bottom": False,
    "axes.grid": False,
    "font.family": "sans-serif",
    "font.size": 9,
})


class DashboardView(ctk.CTkFrame):

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=COLORS["bg"], **kwargs)
        self._last_hash = None   # skip rebuild if data unchanged
        self._build()

    def _build(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text=i18n.t("dashboard.title"),
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["text"],
        ).pack(side="left", padx=18, pady=14)

        ctk.CTkButton(
            header, text="↻ " + i18n.t("actions.refresh"),
            command=self.refresh,
            fg_color="transparent",
            border_color=COLORS["border"],
            border_width=1,
            text_color=COLORS["text_dim"],
            hover_color=COLORS["card_hover"],
            corner_radius=6,
            height=32, width=130,
            font=ctk.CTkFont(size=12),
        ).pack(side="right", padx=18)

        # Scrollable area
        scroll = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        scroll.pack(fill="both", expand=True)
        self._scroll = scroll

        self.refresh()

    def refresh(self):
        games = repo.get_all()
        # Only rebuild if data actually changed
        import hashlib, json
        h = hashlib.md5(json.dumps(
            [(g.id, g.priority, g.price.current if g.price else 0) for g in games]
        ).encode()).hexdigest()
        if h == self._last_hash:
            return
        self._last_hash = h

        for w in self._scroll.winfo_children():
            w.destroy()

        if not games:
            ctk.CTkLabel(
                self._scroll,
                text=i18n.t("dashboard.no_data"),
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_dim"],
            ).pack(pady=60)
            return

        self._render_economic_cards(games)
        self._render_charts(games)

    def _render_economic_cards(self, games):
        total     = len(games)
        on_sale   = sum(1 for g in games if g.price and g.price.is_on_sale)
        s_count   = sum(1 for g in games if g.priority == "S")
        total_val = sum(g.price.current for g in games if g.price)
        # Savings = what you save RIGHT NOW on games that are on sale
        savings   = sum(
            g.price.base - g.price.current
            for g in games
            if g.price and g.price.is_on_sale and g.price.base > g.price.current
        )
        currency  = next((g.price.currency for g in games if g.price), "USD")

        frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        frame.pack(fill="x", padx=16, pady=(16, 0))

        import data.purchase_repository as purchases
        total_spent = purchases.total_spent()
        total_saved = purchases.total_saved()
        bought_count = len(purchases.get_all())

        cards = [
            (i18n.t("stats.total_games"), str(total),                    BLUE),
            (i18n.t("stats.total_value"), f"${total_val:,.0f} {currency}", TEXT),
            (i18n.t("stats.savings"),     f"${savings:,.0f} {currency}", GREEN),
            ("Games bought",              str(bought_count),              GOLD),
            ("Total spent",               f"${total_spent:,.0f}",         BLUE),
            ("All-time saved",            f"${total_saved:,.0f}",         GREEN),
        ]
        for label, value, color in cards:
            card = ctk.CTkFrame(frame, fg_color=CARD_BG, corner_radius=8, border_width=1, border_color=COLORS["border"])
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=10), text_color=TEXT_DIM).pack(anchor="w", padx=12, pady=(10, 0))
            ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=18, weight="bold"), text_color=color).pack(anchor="w", padx=12, pady=(2, 10))

    def _render_charts(self, games):
        row1 = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(16, 8))

        row2 = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(0, 8))

        row3 = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row3.pack(fill="x", padx=16, pady=(0, 16))

        self._chart_priority(row1, games)
        self._chart_status(row1, games)
        self._chart_genres(row2, games)
        self._chart_decades(row2, games)
        self._chart_spending(row3)

    def _make_chart_frame(self, parent, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=8, border_width=1, border_color=COLORS["border"])
        frame.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color=BLUE).pack(anchor="w", padx=14, pady=(10, 0))
        return frame

    def _embed_fig(self, parent: ctk.CTkFrame, fig: Figure):
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        plt.close(fig)

    def _chart_priority(self, parent, games):
        frame = self._make_chart_frame(parent, i18n.t("dashboard.priorities"))
        counts = {p: sum(1 for g in games if g.priority == p) for p in ("S", "A", "B", "C")}
        labels = [f"{p} ({v})" for p, v in counts.items() if v > 0]
        values = [v for v in counts.values() if v > 0]
        colors = [PRIORITY_PALETTE[i] for i, v in enumerate(counts.values()) if v > 0]

        if not values:
            return

        fig, ax = plt.subplots(figsize=(3.5, 2.8), facecolor=CARD_BG)
        ax.set_facecolor(CARD_BG)
        wedges, texts, autotexts = ax.pie(
            values, labels=None, colors=colors,
            autopct="%1.0f%%", startangle=90,
            wedgeprops={"linewidth": 1.5, "edgecolor": BG},
            pctdistance=0.75,
        )
        for at in autotexts:
            at.set_color(BG)
            at.set_fontsize(9)
            at.set_fontweight("bold")

        ax.legend(labels, loc="lower center", ncol=4, frameon=False,
                  fontsize=8, labelcolor=TEXT, bbox_to_anchor=(0.5, -0.08))
        fig.tight_layout(pad=0.5)
        self._embed_fig(frame, fig)

    def _chart_status(self, parent, games):
        frame = self._make_chart_frame(parent, "Prioridad S/A/B/C")
        counts = {p: sum(1 for g in games if g.priority == p) for p in ("S", "A", "B", "C")}
        total = sum(counts.values())

        fig, ax = plt.subplots(figsize=(3.5, 2.8), facecolor=CARD_BG)
        ax.set_facecolor(CARD_BG)

        priorities = list(counts.keys())
        values = list(counts.values())
        bars = ax.barh(priorities, values, color=PRIORITY_PALETTE, height=0.55,
                       linewidth=0)
        ax.set_xlim(0, max(values) * 1.3 if values else 1)
        ax.set_yticks(range(len(priorities)))
        ax.set_yticklabels(priorities, color=TEXT, fontsize=10, fontweight="bold")
        ax.set_xticks([])
        ax.tick_params(length=0)

        for bar, val in zip(bars, values):
            ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                    str(val), va="center", color=TEXT, fontsize=9, fontweight="bold")

        fig.tight_layout(pad=0.5)
        self._embed_fig(frame, fig)

    def _chart_genres(self, parent, games):
        frame = self._make_chart_frame(parent, i18n.t("dashboard.genres"))
        genres: dict[str, int] = {}
        for g in games:
            for genre in g.genre.split(","):
                genre = genre.strip()
                if genre:
                    genres[genre] = genres.get(genre, 0) + 1

        top_genres = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:8]
        if not top_genres:
            return

        labels = [item[0] for item in top_genres]
        values = [item[1] for item in top_genres]
        colors = GENRE_PALETTE[:len(labels)]

        fig, ax = plt.subplots(figsize=(5.5, 2.8), facecolor=CARD_BG)
        ax.set_facecolor(CARD_BG)
        bars = ax.bar(labels, values, color=colors, width=0.6, linewidth=0)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right", color=TEXT_DIM, fontsize=8)
        ax.set_yticks([])
        ax.tick_params(length=0)

        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                    str(val), ha="center", va="bottom", color=TEXT, fontsize=8, fontweight="bold")

        fig.tight_layout(pad=0.5)
        self._embed_fig(frame, fig)

    def _chart_decades(self, parent, games):
        frame = self._make_chart_frame(parent, i18n.t("dashboard.decades"))
        decades: dict[str, int] = {}
        for g in games:
            if g.release_year:
                decade = f"{(g.release_year // 10) * 10}s"
                decades[decade] = decades.get(decade, 0) + 1

        if not decades:
            return

        decades = dict(sorted(decades.items()))
        labels = list(decades.keys())
        values = list(decades.values())
        colors = DECADE_PALETTE[:len(labels)]

        fig, ax = plt.subplots(figsize=(5.5, 2.8), facecolor=CARD_BG)
        ax.set_facecolor(CARD_BG)
        bars = ax.bar(labels, values, color=colors, width=0.55, linewidth=0)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, color=TEXT_DIM, fontsize=9)
        ax.set_yticks([])
        ax.tick_params(length=0)

        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                    str(val), ha="center", va="bottom", color=TEXT, fontsize=9, fontweight="bold")

        fig.tight_layout(pad=0.5)
        self._embed_fig(frame, fig)

    def _chart_spending(self, parent):
        """Bar chart: what you paid vs full price, grouped by month. Plus summary cards."""
        import data.purchase_repository as purchases
        all_purchases = purchases.get_all()

        if not all_purchases:
            frame = self._make_chart_frame(parent, "Purchase History — No purchases yet")
            ctk.CTkLabel(
                frame,
                text="Click 'I bought this game' on any game detail to track purchases.",
                font=ctk.CTkFont(size=11),
                text_color=TEXT_DIM,
            ).pack(pady=20, padx=14)
            return

        # ── Summary cards ─────────────────────────────────────────
        total_paid  = purchases.total_spent()
        total_base  = purchases.total_base()
        total_saved = purchases.total_saved()
        currency    = all_purchases[0].currency if all_purchases else "USD"
        avg_disc    = int(total_saved / total_base * 100) if total_base > 0 else 0

        summary = ctk.CTkFrame(parent, fg_color="transparent")
        summary.pack(side="left", fill="y", padx=(0, 12))
        summary.configure(width=180)

        for label, value, color in [
            ("Total spent",    f"${total_paid:,.0f} {currency}",  BLUE),
            ("Full price was", f"${total_base:,.0f} {currency}",  TEXT_DIM),
            ("Total saved",    f"${total_saved:,.0f} {currency}", GREEN),
            ("Avg. discount",  f"{avg_disc}%",                    GOLD),
            ("Games bought",   str(len(all_purchases)),           TEXT),
        ]:
            card = ctk.CTkFrame(summary, fg_color=CARD_BG,
                                corner_radius=6, border_width=1,
                                border_color="#27272a")
            card.pack(fill="x", pady=(0, 6))
            ctk.CTkLabel(card, text=label,
                         font=ctk.CTkFont(size=9),
                         text_color=TEXT_DIM).pack(anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(card, text=value,
                         font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=color).pack(anchor="w", padx=10, pady=(0, 6))

        # ── Bar chart: paid vs base per game ──────────────────────
        frame = self._make_chart_frame(parent, "Paid vs. Full Price per Purchase")

        # Sort by purchase date
        sorted_p = sorted(all_purchases, key=lambda p: p.purchased_at)
        names    = [p.name[:16] + ("…" if len(p.name) > 16 else "") for p in sorted_p]
        paid_v   = [p.price_paid  for p in sorted_p]
        base_v   = [p.base_price  for p in sorted_p]
        x        = range(len(names))

        fig, ax = plt.subplots(figsize=(max(4.5, len(names)*0.8), 3.0), facecolor=CARD_BG)
        ax.set_facecolor(CARD_BG)

        width = 0.38
        bars_base = ax.bar([i - width/2 for i in x], base_v,
                           width=width, color="#27272a", label="Full price", linewidth=0)
        bars_paid = ax.bar([i + width/2 for i in x], paid_v,
                           width=width, color=BLUE, label="Paid", linewidth=0)

        # Savings labels on top of paid bars
        for bar, p in zip(bars_paid, sorted_p):
            if p.discount_pct > 0:
                ax.text(bar.get_x() + bar.get_width()/2,
                        bar.get_height() + 0.5,
                        f"-{p.discount_pct}%",
                        ha="center", va="bottom",
                        color=GREEN, fontsize=7, fontweight="bold")

        ax.set_xticks(list(x))
        ax.set_xticklabels(names, rotation=30, ha="right",
                           color=TEXT_DIM, fontsize=7)
        ax.set_yticks([])
        ax.tick_params(length=0)
        ax.legend(frameon=False, fontsize=8, labelcolor=TEXT,
                  loc="upper right")

        # Edition badges under each game name
        for i, p in enumerate(sorted_p):
            if p.edition != "Standard":
                ax.text(i, -max(base_v)*0.12, p.edition[:3].upper(),
                        ha="center", va="top",
                        color=GOLD, fontsize=6, style="italic")

        fig.tight_layout(pad=0.5)
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        plt.close(fig)