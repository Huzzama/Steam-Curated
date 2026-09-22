"""
Recap — your year in Steam purchases: a hero card with the headline numbers,
stat tiles (spent / saved / average discount / best deal), monthly spend,
genre and play-status breakdowns, the list of games bought that year and the
all-time totals.

    RecapView(parent, **deps)
    view.refresh(force=False)     reload purchases + games (sync, in memory)
    view.retranslate()            re-render with the current locale

Year selection is a Segmented in the header built from the years that have
purchases. With no purchases at all the view shows one EmptyState.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

import i18n
import data.purchase_repository as purchases
import data.repository as repo
from data.models import Game, Purchase
from ui import image_cache
from ui.animations import clear_layout
from ui.charts import SERIES, BarChart, DonutChart, Sparkline
from ui.components import (Card, CoverImage, EmptyState, ListRow, Pill, SectionHeader, Segmented,
                           StatCard, SubHeader, hbox, label, scroll_area, vbox)
from ui.dashboard_view import genre_counts, genre_label, money_fit, set_stat
from ui.format import count, day, discount, money, pct
from ui.theme import C, SP

_GENRES_N = 6
_PLAY_STATUSES = ("playing", "completed", "on_hold", "abandoned")
COVER_W, COVER_H = 40, 54


def _year(p: Purchase) -> str:
    return (p.purchased_at or "")[:4]


def _currency(items: list[Purchase], fallback: str = "USD") -> str:
    c = Counter(p.currency for p in items if p.currency)
    return c.most_common(1)[0][0] if c else fallback


class RecapView(QWidget):
    """Yearly purchase recap with a year switcher."""

    def __init__(self, parent=None, **deps):
        super().__init__(parent)
        self._open_detail_dep: Optional[Callable] = deps.get("open_detail")
        self._all: list[Purchase] = []
        self._games: dict[str, Game] = {}
        self._year: str = str(datetime.now().year)
        self._hash: Optional[str] = None
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["xl"]), SP["lg"])
        self._header = SectionHeader(i18n.t("recap.title"), "")
        root.addWidget(self._header)
        self._years: Optional[Segmented] = None

        self._content = QWidget()
        self._lay = vbox(self._content, (0, 0, SP["sm"], 0), SP["lg"])
        root.addWidget(scroll_area(self._content), 1)

    # ── shell contract ───────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> None:
        bought = purchases.get_all()
        games = repo.get_all()
        sig = hashlib.md5(json.dumps(
            [(p.app_id, p.price_paid, p.purchased_at, p.edition) for p in bought]
            + [(g.app_id, g.genre, g.play_status, g.cover_path) for g in games]
        ).encode()).hexdigest()
        if not force and sig == self._hash:
            return
        self._hash = sig
        self._all = bought
        self._games = {g.app_id: g for g in games if g.app_id}
        years = self._years_available()
        if self._year not in years:
            self._year = years[0]
        self._rebuild_years(years)
        self._render()

    def retranslate(self) -> None:
        self._header.title.setText(i18n.t("recap.title"))
        self._render()

    # ── year switcher ────────────────────────────────────────────────────────

    def _years_available(self) -> list[str]:
        years = sorted({_year(p) for p in self._all if _year(p)}, reverse=True)
        return years or [str(datetime.now().year)]

    def _rebuild_years(self, years: list[str]) -> None:
        if self._years is not None:
            self._header.actions.removeWidget(self._years)
            self._years.deleteLater()
        self._years = Segmented([(y, y) for y in years], current=self._year)
        self._years.changed.connect(self._on_year)
        self._header.actions.addWidget(self._years)
        self._years.setVisible(len(years) > 1)

    def _on_year(self, year: str) -> None:
        self._year = year
        self._render()

    # ── render ───────────────────────────────────────────────────────────────

    def _render(self) -> None:
        clear_layout(self._lay)
        year = self._year
        yp = sorted((p for p in self._all if _year(p) == year), key=lambda p: p.purchased_at or "", reverse=True)
        first = min((_year(p) for p in self._all if _year(p)), default=year)
        n_all = count(len(self._all), "recap.purchases_one", "recap.purchases_other")
        self._header.subtitle.setText(i18n.t("recap.subtitle", purchases=n_all, year=first) if self._all else n_all)
        self._header.subtitle.setVisible(True)

        if not self._all:
            self._lay.addWidget(EmptyState("sparkles", i18n.t("recap.empty_title"), i18n.t("recap.empty_subtitle")))
            return
        if not yp:
            self._lay.addWidget(EmptyState("calendar", i18n.t("recap.no_data", year=year),
                                           i18n.t("recap.pick_year")))
            return

        cur = _currency(yp)
        by_month = self._by_month(yp)
        self._lay.addWidget(self._hero(year, yp, cur, by_month))
        self._lay.addWidget(self._stats(year, yp, cur))

        cols = hbox(spacing=SP["lg"])
        left, right = vbox(spacing=SP["sm"]), vbox(spacing=SP["sm"])
        left.addWidget(self._monthly_block(by_month, cur))
        left.addWidget(self._genre_block(yp))
        left.addStretch()
        right.addWidget(self._games_block(yp))
        right.addWidget(self._play_block(yp))
        right.addStretch()
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        self._lay.addLayout(cols)

        self._lay.addWidget(self._all_time())
        self._lay.addStretch()

    # ── pieces ───────────────────────────────────────────────────────────────

    @staticmethod
    def _by_month(yp: list[Purchase]) -> list[float]:
        totals = [0.0] * 12
        for p in yp:
            try:
                totals[int(p.purchased_at[5:7]) - 1] += p.price_paid
            except (ValueError, IndexError, TypeError):
                continue
        return totals

    def _hero(self, year: str, yp: list[Purchase], cur: str, by_month: list[float]) -> Card:
        card = Card(padding=SP["xl"], spacing=0)
        row = hbox(spacing=SP["xl"])
        col = vbox(spacing=SP["xs"])
        col.addWidget(label(i18n.t("recap.this_year", year=year).upper(), "eyebrow", color=C["accent"]))
        headline = hbox(spacing=SP["md"])
        headline.addWidget(label(str(len(yp)), "value", size="3xl", color=C["text"]), 0,
                           Qt.AlignmentFlag.AlignBottom)
        word = label(i18n.t("recap.hero_count_one" if len(yp) == 1 else "recap.hero_count_other"),
                     "h2", color=C["text_2"])
        word.setContentsMargins(0, 0, 0, SP["xs"] + 2)          # sit on the numeral's baseline
        headline.addWidget(word, 0, Qt.AlignmentFlag.AlignBottom)
        headline.addStretch()
        col.addLayout(headline)
        saved = sum(p.saved for p in yp)
        if saved > 0:
            col.addWidget(label(i18n.t("recap.hero_saved", amount=money(saved, cur)), "body", color=C["green"]))
        else:
            col.addWidget(label(i18n.t("recap.hero_full_price"), "dim"))
        row.addLayout(col, 1)

        spark_col = vbox(spacing=SP["xs"])
        spark_col.addStretch()
        spark = Sparkline(by_month, "accent", height=56)
        spark.setFixedWidth(240)
        spark_col.addWidget(spark)
        spark_col.addWidget(label(i18n.t("recap.spark_caption", amount=money(sum(by_month), cur)), "muted",
                                  align=Qt.AlignmentFlag.AlignRight))
        row.addLayout(spark_col)
        card.body.addLayout(row)
        return card

    def _stats(self, year: str, yp: list[Purchase], cur: str) -> QWidget:
        row = QWidget()
        lay = hbox(row, spacing=SP["md"])
        spent = sum(p.price_paid for p in yp)
        saved = sum(p.saved for p in yp)
        base = sum(p.base_price for p in yp)
        best = max(yp, key=lambda p: (p.discount_pct, p.saved))
        fmt = lambda v: money_fit(v, cur)  # noqa: E731

        a = StatCard(i18n.t("recap.spent", year=year), icon="shopping-cart", tone="accent",
                     caption=i18n.t("recap.avg_per_game_caption", amount=money(spent / len(yp), cur)))
        set_stat(a, spent, fmt)
        b = StatCard(i18n.t("recap.saved", year=year), icon="piggy-bank", tone="green",
                     caption=i18n.t("recap.full_price_caption", amount=money_fit(base, cur)))
        set_stat(b, saved, fmt)
        c = StatCard(i18n.t("recap.avg_discount"), icon="percent", tone="gold",
                     caption=count(len(yp), "recap.purchases_one", "recap.purchases_other"))
        set_stat(c, saved / base * 100 if base else 0, lambda v: pct(v))
        d = StatCard(i18n.t("recap.best_deal"), icon="trophy", tone="pink", caption=best.name)
        set_stat(d, float(best.discount_pct), lambda v: discount(round(v)) if v >= 1 else pct(0))
        for tile in (a, b, c, d):
            lay.addWidget(tile, 1)
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

    def _monthly_block(self, by_month: list[float], cur: str) -> QWidget:
        labels = [i18n.t(f"months.{m}")[:3] for m in range(1, 13)]
        chart = BarChart(labels, by_month, "accent", height=170)
        chart.set_formatter(lambda v: money_fit(v, cur) if v > 0 else "")
        peak = max(range(12), key=lambda i: by_month[i])
        caption = label(i18n.t("recap.peak_month", month=i18n.t(f"months.{peak + 1}")), "muted") \
            if by_month[peak] > 0 else None
        return self._block(i18n.t("recap.monthly_spending"), self._chart_card(chart), caption)

    def _genre_block(self, yp: list[Purchase]) -> QWidget:
        games = [self._games[p.app_id] for p in yp if p.app_id in self._games]
        counts, raw = genre_counts(games)
        top = counts.most_common(_GENRES_N)
        slices = [(genre_label(k, raw), v, SERIES[i]) for i, (k, v) in enumerate(top)]
        chart = DonutChart(slices, center_caption=i18n.t("recap.genres_short"))
        chart.set_empty_text(i18n.t("recap.no_genres"))
        return self._block(i18n.t("recap.genres"), self._chart_card(chart))

    def _play_block(self, yp: list[Purchase]) -> QWidget:
        games = [self._games[p.app_id] for p in yp if p.app_id in self._games]
        c = Counter((g.play_status or "") for g in games)
        keys = list(_PLAY_STATUSES) + [""]
        labels = [i18n.t(f"play_status.{k}") if k else i18n.t("recap.not_started") for k in keys]
        values = [c.get(k, 0) for k in keys]
        colors = [C["accent"], C["green"], C["gold"], C["red"], C["text_muted"]]
        chart = BarChart(labels, values, "violet", horizontal=True, colors=colors)
        chart.set_empty_text(i18n.t("recap.no_genres"))
        caption = label(count(len(games), "recap.games_one", "recap.games_other"), "muted")
        return self._block(i18n.t("recap.play_status"), self._chart_card(chart), caption)

    def _games_block(self, yp: list[Purchase]) -> QWidget:
        body = QWidget()
        lay = vbox(body, spacing=SP["sm"])
        std = i18n.t("mark_purchased.standard_edition")
        for p in yp:
            g = self._games.get(p.app_id)
            cover = CoverImage(COVER_W, COVER_H, radius=SP["sm"])
            cover.set_pixmap(image_cache.get(g.cover_path, (COVER_W, COVER_H)) if g else None)
            trailing = QWidget()
            tl = hbox(trailing, spacing=SP["sm"])
            col = vbox(spacing=0)
            col.addWidget(label(money(p.price_paid, p.currency), "mono", align=Qt.AlignmentFlag.AlignRight))
            if p.saved > 0:
                col.addWidget(label(i18n.t("recap.saved_inline", amount=money(p.saved, p.currency)), "muted",
                                    color=C["green"], align=Qt.AlignmentFlag.AlignRight))
            tl.addLayout(col)
            if p.discount_pct > 0:
                tl.addWidget(Pill(discount(p.discount_pct), "green"), 0, Qt.AlignmentFlag.AlignVCenter)
            edition = p.edition if p.edition and p.edition.lower() not in (std.lower(), "standard") else ""
            sub = " · ".join(b for b in (edition, day(p.purchased_at)) if b)
            row = ListRow(p.name, sub, leading=cover, trailing=trailing, clickable=g is not None)
            if g is not None:
                row.clicked.connect(lambda g=g: self._open(g))
            lay.addWidget(row)
        caption = label(count(len(yp), "recap.games_one", "recap.games_other"), "muted")
        return self._block(i18n.t("recap.games_bought"), body, caption)

    def _all_time(self) -> QWidget:
        cur = _currency(self._all)
        spent = sum(p.price_paid for p in self._all)
        saved = sum(p.saved for p in self._all)
        n = len(self._all)
        row = QWidget()
        lay = hbox(row, spacing=SP["md"])
        fmt = lambda v: money_fit(v, cur)  # noqa: E731
        a = StatCard(i18n.t("recap.total_spent"), icon="wallet", tone="accent"); set_stat(a, spent, fmt)
        b = StatCard(i18n.t("recap.total_saved"), icon="piggy-bank", tone="green"); set_stat(b, saved, fmt)
        c = StatCard(i18n.t("recap.games_count"), icon="gamepad-2", tone="gold"); set_stat(c, n)
        d = StatCard(i18n.t("recap.avg_per_game"), icon="calculator", tone="violet")
        set_stat(d, spent / n if n else 0, fmt)
        for tile in (a, b, c, d):
            lay.addWidget(tile, 1)
        return self._block(i18n.t("recap.all_time"), row)

    # ── actions ──────────────────────────────────────────────────────────────

    def _open(self, game: Game) -> None:
        fn = self._open_detail_dep or getattr(self.window(), "open_detail", None)
        if fn:
            fn(game)
