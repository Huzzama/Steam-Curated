"""
Dashboard — the wishlist at a glance: stat tiles, three QPainter charts
(priority, genres, discount buckets) and three short lists (best deals,
recently added, latest purchases).

    DashboardView(parent, **deps)
    view.refresh(force=False)     recompute from the repositories (sync, cheap)
    view.retranslate()            re-render with the current locale

Everything is computed from data.repository / data.purchase_repository in
memory — no network, no threads. Rows open the detail panel through the
`open_detail` dep (or the window's `open_detail` when the shell passes none).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

import i18n
import data.purchase_repository as purchases
import data.repository as repo
from data.models import Game, Purchase
from data.status import STATUS_PURCHASED, normalize_status
from ui import image_cache
from ui.animations import clear_layout
from ui.charts import BarChart, DonutChart
from ui.components import (Button, Card, CoverImage, EmptyState, ListRow, Pill, PriorityBadge,
                           SectionHeader, StatCard, SubHeader, hbox, label, scroll_area, vbox)
from ui.format import compact, count, day, discount, money
from ui.theme import C, PRIORITY, SP

PRIORITIES = ("S", "A", "B", "C")
_LIST_N = 5
_GENRES_N = 8
_BUCKETS = (("bucket_1", 1, 24), ("bucket_25", 25, 49), ("bucket_50", 50, 74), ("bucket_75", 75, 100))
_NON_WORD = re.compile(r"[^a-z0-9]+")

COVER_W, COVER_H = 36, 48


# ── helpers shared with Recap / History ───────────────────────────────────────

def money_fit(amount: float, currency: str) -> str:
    """money() for a stat tile: sums >= 10 000 are compacted so the big mono
    value never overflows the card; symbol placement follows money()."""
    if abs(amount) < 10_000:
        return money(amount, currency)
    sample = money(1, currency)
    num = "1.00" if "1.00" in sample else "1"
    return sample.replace(num, compact(amount), 1)


def genre_key(genre: str) -> str:
    """'Real-Time Strategy' → 'real_time_strategy' (matches locales genres.*)."""
    return _NON_WORD.sub("_", genre.strip().lower()).strip("_")


def translate_genre(genre: str) -> str:
    """Localized genre name when locales/genres has it, else the raw string."""
    g = (genre or "").strip()
    if not g:
        return g
    key = genre_key(g)
    t = i18n.t(f"genres.{key}")
    return g if t.startswith("genres.") else t


def genre_counts(games: list[Game]) -> tuple[Counter, dict[str, str]]:
    """(Counter of normalized genre keys, key → raw name as Steam spells it)."""
    c: Counter = Counter()
    raw: dict[str, str] = {}
    for g in games:
        for part in (g.genre or "").split(","):
            k = genre_key(part)
            if k:
                c[k] += 1
                raw.setdefault(k, part.strip())
    return c, raw


def genre_label(key: str, raw: Optional[dict[str, str]] = None) -> str:
    """Localized name for a normalized genre key, else the raw Steam string."""
    t = i18n.t(f"genres.{key}")
    if not t.startswith("genres."):
        return t
    return (raw or {}).get(key) or key.replace("_", " ").title()


def set_stat(card: StatCard, value: float, fmt: Optional[Callable[[float], str]] = None) -> None:
    """StatCard.set_value that also renders 0 (the count-up animation never
    emits when start == end, leaving the placeholder dash)."""
    card.set_value(value, fmt, animate=bool(value))


def is_purchased(g: Game) -> bool:
    return normalize_status(g.status) == STATUS_PURCHASED


def on_sale(g: Game) -> bool:
    return g.price is not None and g.price.is_on_sale and g.price.discount_pct > 0


def dominant_currency(games: list[Game], fallback: str = "USD") -> str:
    c = Counter(g.price.currency for g in games if g.price and g.price.currency)
    return c.most_common(1)[0][0] if c else fallback


# ── view ──────────────────────────────────────────────────────────────────────

class DashboardView(QWidget):
    """Stats, charts and short lists computed from the local repositories."""

    def __init__(self, parent=None, **deps):
        super().__init__(parent)
        self._open_detail_dep: Optional[Callable] = deps.get("open_detail")
        self._open_add_dep: Optional[Callable] = deps.get("open_add_dialog")
        self._games: list[Game] = []
        self._purchases: list[Purchase] = []
        self._hash: Optional[str] = None
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["xl"]), SP["lg"])
        self._header = SectionHeader(i18n.t("dashboard.title"), "")
        root.addWidget(self._header)

        self._content = QWidget()
        self._lay = vbox(self._content, (0, 0, SP["sm"], 0), SP["lg"])
        root.addWidget(scroll_area(self._content), 1)

    # ── shell contract ───────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> None:
        games = repo.get_all()
        bought = purchases.get_all()
        sig = hashlib.md5(json.dumps(
            [(g.id, g.priority, g.status, g.genre, g.date_added,
              g.price.current if g.price else None, g.price.discount_pct if g.price else None) for g in games]
            + [(p.app_id, p.price_paid, p.purchased_at) for p in bought]
        ).encode()).hexdigest()
        if not force and sig == self._hash:
            return
        self._hash = sig
        self._games, self._purchases = games, bought
        self._render()

    def retranslate(self) -> None:
        self._header.title.setText(i18n.t("dashboard.title"))
        self._render()

    # ── render ───────────────────────────────────────────────────────────────

    def _render(self) -> None:
        clear_layout(self._lay)
        games = self._games
        now = datetime.now()
        self._header.subtitle.setText(i18n.t("dashboard.subtitle",
                                             games=count(len(games), "dashboard.games_one", "dashboard.games_other"),
                                             date=day(now), time=now.strftime("%H:%M")))
        self._header.subtitle.setVisible(True)

        if not games:
            self._lay.addWidget(EmptyState("layout-dashboard", i18n.t("dashboard.empty_title"),
                                           i18n.t("dashboard.empty_subtitle"),
                                           action=Button(i18n.t("actions.add"), "primary", "plus",
                                                         on_click=self._add_game)))
            return

        active = [g for g in games if not is_purchased(g)]
        currency = dominant_currency(active or games)
        self._lay.addWidget(self._stats(games, active, currency))

        # two independent columns so blocks of different heights never leave gaps
        cols = hbox(spacing=SP["lg"])
        left, right = vbox(spacing=SP["sm"]), vbox(spacing=SP["sm"])
        left.addWidget(self._priority_block(games))
        left.addWidget(self._discount_block(active))
        left.addWidget(self._recent_block(games))
        left.addStretch()
        right.addWidget(self._genre_block(games))
        right.addWidget(self._deals_block(active))
        right.addWidget(self._purchases_block(games, currency))
        right.addStretch()
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        self._lay.addLayout(cols)
        self._lay.addStretch()

    # ── blocks ───────────────────────────────────────────────────────────────

    def _stats(self, games: list[Game], active: list[Game], currency: str) -> QWidget:
        row = QWidget()
        lay = hbox(row, spacing=SP["md"])
        bought = sum(1 for g in games if is_purchased(g))
        sale = [g for g in active if on_sale(g)]
        value = sum(g.price.current for g in active if g.price)
        savings = sum(g.price.base - g.price.current for g in sale if g.price.base > g.price.current)
        priced = sum(1 for g in active if g.price)
        fmt = lambda v: money_fit(v, currency)  # noqa: E731

        tiles = [
            ("stats.total_games", len(games), "heart", "accent", None,
             i18n.t("dashboard.purchased_caption", n=bought) if bought else i18n.t("dashboard.all_wishlist")),
            ("stats.on_sale_now", len(sale), "tag", "gold", None,
             i18n.t("dashboard.sale_caption", pct=f"{len(sale) / len(active) * 100:.0f}%" if active else "0%")),
            ("stats.total_value", value, "wallet", "violet", fmt,
             i18n.t("dashboard.value_caption", n=priced)),
            ("stats.savings", savings, "piggy-bank", "green", fmt,
             i18n.t("dashboard.savings_caption") if savings > 0 else i18n.t("dashboard.no_savings")),
        ]
        for key, val, icon, tone, f, caption in tiles:
            card = StatCard(i18n.t(key), icon=icon, tone=tone, caption=caption)
            set_stat(card, val, f)
            lay.addWidget(card, 1)
        return row

    @staticmethod
    def _block(title: str, body: QWidget, trailing: Optional[QWidget] = None) -> QWidget:
        w = QWidget()
        lay = vbox(w, spacing=SP["xs"])
        lay.addWidget(SubHeader(title, trailing))
        lay.addWidget(body)
        return w

    @staticmethod
    def _chart_card(chart: QWidget) -> Card:
        card = Card(padding=SP["lg"], spacing=0)
        card.body.addWidget(chart)
        return card

    def _priority_block(self, games: list[Game]) -> QWidget:
        counts = Counter(g.priority for g in games)
        slices = [(i18n.t(f"priority.{p}"), counts.get(p, 0), PRIORITY[p]) for p in PRIORITIES]
        chart = DonutChart(slices, center_caption=i18n.t("dashboard.games_short"))
        return self._block(i18n.t("dashboard.priorities"), self._chart_card(chart))

    def _genre_block(self, games: list[Game]) -> QWidget:
        counts, raw = genre_counts(games)
        top = counts.most_common(_GENRES_N)
        chart = BarChart([genre_label(k, raw) for k, _ in top], [v for _, v in top], "accent", horizontal=True)
        caption = label(i18n.t("dashboard.top_n", n=len(top)), "muted") if top else None
        return self._block(i18n.t("dashboard.genres"), self._chart_card(chart), caption)

    def _discount_block(self, active: list[Game]) -> QWidget:
        priced = [g for g in active if g.price]
        labels = [i18n.t("dashboard.bucket_none")] + [i18n.t(f"dashboard.{k}") for k, _, _ in _BUCKETS]
        values = [sum(1 for g in priced if not on_sale(g))]
        for _, lo, hi in _BUCKETS:
            values.append(sum(1 for g in priced if on_sale(g) and lo <= g.price.discount_pct <= hi))
        chart = BarChart(labels, values, "green", height=176)
        caption = label(count(len(priced), "dashboard.games_one", "dashboard.games_other"), "muted")
        return self._block(i18n.t("dashboard.discounts"), self._chart_card(chart), caption)

    def _deals_block(self, active: list[Game]) -> QWidget:
        deals = sorted((g for g in active if on_sale(g)), key=lambda g: g.price.discount_pct, reverse=True)[:_LIST_N]
        body = QWidget()
        lay = vbox(body, spacing=SP["sm"])
        if not deals:
            lay.addWidget(EmptyState("tag", i18n.t("dashboard.no_deals_title"), i18n.t("dashboard.no_deals_subtitle")))
        for g in deals:
            trailing = QWidget()
            tl = hbox(trailing, spacing=SP["sm"])
            col = vbox(spacing=0)
            price = label(money(g.price.current, g.price.currency), "mono", color=C["green"],
                          align=Qt.AlignmentFlag.AlignRight)
            base = label(money(g.price.base, g.price.currency), "muted", align=Qt.AlignmentFlag.AlignRight)
            base.setProperty("role", "mono")
            _strike(base)
            col.addWidget(price); col.addWidget(base)
            tl.addLayout(col)
            tl.addWidget(Pill(discount(g.price.discount_pct), "green"), 0, Qt.AlignmentFlag.AlignVCenter)
            sub = " · ".join(b for b in (translate_genre((g.genre or "").split(",")[0]), g.developer) if b)
            row = ListRow(g.name, sub, leading=PriorityBadge(g.priority), trailing=trailing)
            row.clicked.connect(lambda g=g: self._open(g))
            lay.addWidget(row)
        return self._block(i18n.t("dashboard.best_deals"), body,
                           label(count(len(deals), "dashboard.games_one", "dashboard.games_other"), "muted") if deals else None)

    def _recent_block(self, games: list[Game]) -> QWidget:
        recent = sorted(games, key=lambda g: (g.date_added or "", g.id), reverse=True)[:_LIST_N]
        body = QWidget()
        lay = vbox(body, spacing=SP["sm"])
        if not recent:
            lay.addWidget(EmptyState("clock-fading", i18n.t("history.empty")))
        for g in recent:
            trailing = QWidget()
            tl = hbox(trailing, spacing=SP["sm"])
            if g.price:
                tl.addWidget(label(money(g.price.current, g.price.currency), "mono",
                                   color=C["green"] if on_sale(g) else C["text"]))
            tl.addWidget(label(day(g.date_added), "muted"))
            sub = " · ".join(b for b in (translate_genre((g.genre or "").split(",")[0]),
                                          str(g.release_year) if g.release_year else "") if b)
            row = ListRow(g.name, sub, leading=PriorityBadge(g.priority), trailing=trailing)
            row.clicked.connect(lambda g=g: self._open(g))
            lay.addWidget(row)
        return self._block(i18n.t("dashboard.recently_added"), body)

    def _purchases_block(self, games: list[Game], currency: str) -> QWidget:
        bought = sorted(self._purchases, key=lambda p: p.purchased_at or "", reverse=True)
        cur = bought[0].currency if bought else currency
        body = QWidget()
        lay = vbox(body, spacing=SP["sm"])

        tiles = hbox(spacing=SP["md"])
        spent = StatCard(i18n.t("dashboard.total_spent"), icon="shopping-cart", tone="accent",
                         caption=count(len(bought), "dashboard.purchases_one", "dashboard.purchases_other"))
        set_stat(spent, sum(p.price_paid for p in bought), lambda v: money_fit(v, cur))
        saved_total = sum(p.saved for p in bought)
        base_total = sum(p.base_price for p in bought)
        saved = StatCard(i18n.t("dashboard.total_saved"), icon="piggy-bank", tone="green",
                         caption=i18n.t("dashboard.avg_discount_caption",
                                        pct=f"{saved_total / base_total * 100:.0f}%") if base_total
                         else i18n.t("dashboard.no_savings"))
        set_stat(saved, saved_total, lambda v: money_fit(v, cur))
        tiles.addWidget(spent, 1); tiles.addWidget(saved, 1)
        lay.addLayout(tiles)

        if not bought:
            lay.addWidget(EmptyState("shopping-cart", i18n.t("dashboard.no_purchases_title"),
                                     i18n.t("dashboard.purchase_summary_hint")))
        by_app = {g.app_id: g for g in games}
        for p in bought[:_LIST_N]:
            g = by_app.get(p.app_id)
            cover = CoverImage(COVER_W, COVER_H, radius=SP["xs"] + 2)
            cover.set_pixmap(image_cache.get(g.cover_path, (COVER_W, COVER_H)) if g else None)
            trailing = QWidget()
            tl = hbox(trailing, spacing=SP["sm"])
            tl.addWidget(label(money(p.price_paid, p.currency), "mono"))
            if p.discount_pct > 0:
                tl.addWidget(Pill(discount(p.discount_pct), "green"), 0, Qt.AlignmentFlag.AlignVCenter)
            std = i18n.t("mark_purchased.standard_edition").lower()
            edition = p.edition if p.edition and p.edition.lower() not in (std, "standard") else ""
            sub = " · ".join(b for b in (edition, day(p.purchased_at)) if b)
            row = ListRow(p.name, sub, leading=cover, trailing=trailing, clickable=g is not None)
            if g is not None:
                row.clicked.connect(lambda g=g: self._open(g))
            lay.addWidget(row)
        return self._block(i18n.t("dashboard.purchases"), body)

    # ── actions ──────────────────────────────────────────────────────────────

    def _open(self, game: Game) -> None:
        fn = self._open_detail_dep or getattr(self.window(), "open_detail", None)
        if fn:
            fn(game)

    def _add_game(self) -> None:
        fn = self._open_add_dep or getattr(self.window(), "open_add_dialog", None)
        if fn:
            fn()


def _strike(lbl) -> None:
    """Strike a label's text (the theme QSS has no text-decoration role)."""
    f = lbl.font()
    f.setStrikeOut(True)
    lbl.setFont(f)
