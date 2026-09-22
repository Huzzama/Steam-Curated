"""
History — every purchase you recorded, newest first, grouped by month.

    HistoryView(parent, on_game_click=None, **deps)
    view.refresh(force=False)     reload purchases + games (sync, in memory)
    view.retranslate()            re-render with the current locale

Header totals · SearchField + Segmented (all / this year / last 12 months) ·
three StatCards for the current range · one ListRow per purchase (cover,
title, edition · date, price paid, struck base price, discount pill, saved)
with a trash IconButton. Deleting asks first, then removes the purchase and
flips the game back to the wishlist on a worker thread through run_async,
and finally calls the shell's `on_data_changed`.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, timedelta
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox, QSizePolicy, QWidget

import i18n
import data.purchase_repository as purchases
import data.repository as repo
from data.models import Game, Purchase
from data.status import STATUS_PURCHASED, STATUS_WISHLIST, normalize_status
from ui import image_cache
from ui.animations import clear_layout
from ui.async_bridge import run_async
from ui.components import (CoverImage, EmptyState, IconButton, ListRow, Pill, SearchField, SectionHeader,
                           Segmented, StatCard, hbox, label, scroll_area, vbox)
from ui.dashboard_view import money_fit, set_stat
from ui.format import count, day, discount, money
from ui.theme import C, SP

RANGES = ("all", "year", "12m")
COVER_W, COVER_H = 40, 54
_SEARCH_DEBOUNCE = 150   # ms


def _currency(items: list[Purchase], fallback: str = "USD") -> str:
    c = Counter(p.currency for p in items if p.currency)
    return c.most_common(1)[0][0] if c else fallback


class HistoryView(QWidget):
    """Purchase history with search, range filter, totals and delete."""

    def __init__(self, parent=None, on_game_click: Optional[Callable[[Game], None]] = None, **deps):
        super().__init__(parent)
        self._on_game_click = on_game_click or deps.get("open_detail")
        self._notify_dep: Optional[Callable] = deps.get("notify")
        self._data_changed_dep: Optional[Callable] = deps.get("on_data_changed")
        self._all: list[Purchase] = []
        self._games: dict[str, Game] = {}
        self._range = "all"
        self._query = ""
        self._hash: Optional[str] = None
        self._busy: set[str] = set()

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE)
        self._search_timer.timeout.connect(self._render)
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["xl"]), SP["lg"])
        self._header = SectionHeader(i18n.t("history.title"), "")
        root.addWidget(self._header)

        self._toolbar = QWidget()
        tb = hbox(self._toolbar, spacing=SP["md"])
        self._search = SearchField(i18n.t("history.search_placeholder"))
        self._search.setMinimumWidth(240)
        self._search.setMaximumWidth(380)
        self._search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._search.textChanged.connect(self._on_search)
        tb.addWidget(self._search)
        self._ranges = Segmented([(k, i18n.t(f"history.range_{k}")) for k in RANGES], current=self._range)
        self._ranges.changed.connect(self._on_range)
        tb.addWidget(self._ranges)
        tb.addStretch()
        root.addWidget(self._toolbar)

        self._content = QWidget()
        self._lay = vbox(self._content, (0, 0, SP["sm"], 0), SP["sm"])
        root.addWidget(scroll_area(self._content), 1)

    # ── shell contract ───────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> None:
        bought = purchases.get_all()
        games = repo.get_all()
        sig = hashlib.md5(json.dumps(
            [(p.app_id, p.price_paid, p.purchased_at, p.edition) for p in bought]
            + [(g.app_id, g.cover_path, g.status) for g in games]
        ).encode()).hexdigest()
        if not force and sig == self._hash:
            return
        self._hash = sig
        self._all = sorted(bought, key=lambda p: p.purchased_at or "", reverse=True)
        self._games = {g.app_id: g for g in games if g.app_id}
        self._render()

    def retranslate(self) -> None:
        self._header.title.setText(i18n.t("history.title"))
        self._search.setPlaceholderText(i18n.t("history.search_placeholder"))
        for k in RANGES:
            self._ranges.set_label(k, i18n.t(f"history.range_{k}"))
        self._render()

    # ── filters ──────────────────────────────────────────────────────────────

    def _on_search(self, text: str) -> None:
        self._query = text.strip().lower()
        self._search_timer.start()

    def _on_range(self, key: str) -> None:
        self._range = key
        self._render()

    def _filtered(self) -> list[Purchase]:
        today = date.today()
        items = self._all
        if self._range == "year":
            items = [p for p in items if (p.purchased_at or "")[:4] == str(today.year)]
        elif self._range == "12m":
            since = (today - timedelta(days=365)).isoformat()
            items = [p for p in items if (p.purchased_at or "") >= since]
        if self._query:
            q = self._query
            items = [p for p in items if q in p.name.lower() or q in (p.edition or "").lower()]
        return items

    # ── render ───────────────────────────────────────────────────────────────

    def _render(self) -> None:
        clear_layout(self._lay)
        cur = _currency(self._all)
        spent_all = sum(p.price_paid for p in self._all)
        saved_all = sum(p.saved for p in self._all)
        self._header.subtitle.setText(i18n.t("history.subtitle_totals",
                                             purchases=count(len(self._all), "history.purchases_one", "history.purchases_other"),
                                             spent=money(spent_all, cur), saved=money(saved_all, cur)))
        self._header.subtitle.setVisible(True)
        self._toolbar.setVisible(bool(self._all))

        if not self._all:
            self._lay.addWidget(EmptyState("shopping-cart", i18n.t("history.empty_title"),
                                           i18n.t("history.empty_subtitle")))
            return

        items = self._filtered()
        self._lay.addWidget(self._stats(items, cur))

        if not items:
            self._lay.addWidget(EmptyState("search", i18n.t("history.no_match_title"),
                                           i18n.t("history.no_match_subtitle")))
            return

        month = None
        for p in items:
            key = (p.purchased_at or "")[:7]
            if key != month:
                month = key
                self._lay.addWidget(self._month_label(key))
            self._lay.addWidget(self._row(p))
        self._lay.addStretch()

    def _stats(self, items: list[Purchase], cur: str) -> QWidget:
        row = QWidget()
        lay = hbox(row, spacing=SP["md"])
        spent = sum(p.price_paid for p in items)
        saved = sum(p.saved for p in items)
        base = sum(p.base_price for p in items)
        scope = i18n.t(f"history.range_{self._range}")
        fmt = lambda v: money_fit(v, cur)  # noqa: E731
        a = StatCard(i18n.t("recap.total_spent"), icon="shopping-cart", tone="accent", caption=scope)
        set_stat(a, spent, fmt)
        b = StatCard(i18n.t("recap.total_saved"), icon="piggy-bank", tone="green",
                     caption=i18n.t("history.avg_discount_caption", pct=f"{saved / base * 100:.0f}%") if base else scope)
        set_stat(b, saved, fmt)
        c = StatCard(i18n.t("recap.games_count"), icon="receipt", tone="gold",
                     caption=i18n.t("history.avg_per_game_caption", amount=money(spent / len(items), cur)) if items else scope)
        set_stat(c, len(items))
        for tile in (a, b, c):
            lay.addWidget(tile, 1)
        return row

    @staticmethod
    def _month_label(key: str) -> QWidget:
        try:
            y, m = key.split("-")
            text = f"{i18n.t(f'months.{int(m)}')} {y}"
        except (ValueError, AttributeError):
            text = key or "—"
        lbl = label(text.upper(), "eyebrow")
        lbl.setContentsMargins(SP["xs"], SP["md"], 0, SP["xs"])
        return lbl

    def _row(self, p: Purchase) -> ListRow:
        g = self._games.get(p.app_id)
        cover = CoverImageThumb(g)
        std = i18n.t("mark_purchased.standard_edition")
        edition = p.edition if p.edition and p.edition.lower() not in (std.lower(), "standard") else std
        sub = " · ".join(b for b in (edition, day(p.purchased_at)) if b)

        trailing = QWidget()
        tl = hbox(trailing, spacing=SP["md"])
        prices = vbox(spacing=0)
        prices.addWidget(label(money(p.price_paid, p.currency), "mono", align=Qt.AlignmentFlag.AlignRight))
        if p.base_price > p.price_paid:
            base = label(money(p.base_price, p.currency), "muted", align=Qt.AlignmentFlag.AlignRight)
            base.setProperty("role", "mono")
            f = base.font(); f.setStrikeOut(True); base.setFont(f)
            prices.addWidget(base)
        tl.addLayout(prices)
        if p.discount_pct > 0:
            tl.addWidget(Pill(discount(p.discount_pct), "green"), 0, Qt.AlignmentFlag.AlignVCenter)
        if p.saved > 0:
            tl.addWidget(label(i18n.t("history.saved_amount", amount=money(p.saved, p.currency)), "muted",
                               color=C["green"]))
        trash = IconButton("trash", i18n.t("history.delete_tooltip"), color=C["text_dim"],
                           on_click=lambda: self._confirm_delete(p))
        trash.setEnabled(p.app_id not in self._busy)
        tl.addWidget(trash)

        row = ListRow(p.name, sub, leading=cover, trailing=trailing, clickable=g is not None)
        if g is None:
            row.setToolTip(i18n.t("history.game_removed"))
        else:
            row.clicked.connect(lambda g=g: self._open(g))
        return row

    # ── actions ──────────────────────────────────────────────────────────────

    def _open(self, game: Game) -> None:
        fn = self._on_game_click or getattr(self.window(), "open_detail", None)
        if fn:
            fn(game)

    def _confirm_delete(self, p: Purchase) -> None:
        if p.app_id in self._busy:
            return
        answer = QMessageBox.question(self, i18n.t("history.delete_title"),
                                      i18n.t("history.delete_text", name=p.name),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._busy.add(p.app_id)

        def work():
            purchases.delete(p.app_id)
            game = repo.get_by_app_id(p.app_id)
            if game is not None and normalize_status(game.status) == STATUS_PURCHASED:
                game.status = STATUS_WISHLIST          # canonical constant, never a translated string
                repo.update(game)
            return p

        def on_done(result):
            self._busy.discard(p.app_id)
            if isinstance(result, Exception):
                self._notify(i18n.t("history.delete_failed", msg=str(result)), "error")
                return
            self._notify(i18n.t("history.deleted", name=p.name), "success")
            fn = self._data_changed_dep or getattr(self.window(), "on_data_changed", None)
            if fn:
                fn()
            else:
                self.refresh(force=True)

        run_async(self, work, on_done=on_done)

    def _notify(self, message: str, tone: str) -> None:
        fn = self._notify_dep or getattr(self.window(), "notify", None)
        if fn:
            fn(message, tone)


def CoverImageThumb(game: Optional[Game]) -> CoverImage:
    """40×54 cover for a purchase row (placeholder when the game is gone)."""
    cover = CoverImage(COVER_W, COVER_H, radius=SP["sm"])
    cover.set_pixmap(image_cache.get(game.cover_path, (COVER_W, COVER_H)) if game else None)
    return cover
