"""
Wishlist — the home view: every tracked game as a GameCard grid, with
search, status / priority filters, sort, and a stat row on top.

    WishlistView(parent, on_add_game=..., on_game_click=...)
    view.refresh(force=False)     reload from the repository and re-render
    view.retranslate()            update visible strings in place

Rendering only builds the cards of the current filter, in chunks driven by a
zero-interval QTimer so 600+ games never freeze the GUI. Bulk price refresh,
cover download and the Excel export run through ui.async_bridge.run_async.
"""
from __future__ import annotations

import re
import threading
from collections import Counter, deque
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QComboBox, QGridLayout, QMenu, QProgressBar, QSizePolicy, QWidget

import i18n
import data.repository as repo
from data.models import Game
from data.status import STATUS_PURCHASED, normalize_status
from ui import icons
from ui.animations import clear_layout
from ui.async_bridge import run_async
from ui.components import (Button, ChipGroup, EmptyState, FlowLayout, IconButton, PriorityBadge,
                           SearchField, SectionHeader, Segmented, StatCard, SubHeader, hbox,
                           label, scroll_area, vbox)
from ui.format import compact, money, pct
from ui.game_card import GameCard
from ui.theme import C, SP

PRIORITIES = ("S", "A", "B", "C")
STATUS_FILTERS = ("all", "sa", "sale", "purchased")
SORTS = ("priority", "name", "price", "discount", "added")

_CHUNK = 16              # cards built per timer tick (~60 ms)
_SEARCH_DEBOUNCE = 150   # ms
_LOW_TOLERANCE = 1.05    # "at all-time low" = within 5 % of the low (same rule as GameCard)
_PRIO_PREFIX = re.compile(r"^[SABC]\s*[—–-]\s*")
_STATS_4COL_MIN = 940    # view width below which the stat tiles wrap 2 × 2


def _is_purchased(g: Game) -> bool:
    return normalize_status(g.status) == STATUS_PURCHASED


def _on_sale(g: Game) -> bool:
    return g.price is not None and g.price.is_on_sale and g.price.discount_pct > 0


def _at_low(g: Game) -> bool:
    p, h = g.price, g.price_history
    return p is not None and h is not None and h.all_time_low > 0 and p.current <= h.all_time_low * _LOW_TOLERANCE


def _money_fit(amount: float, currency: str) -> str:
    """money() for a stat tile: sums >= 10 000 are compacted ('MX$12.3K') so the
    big mono value never overflows the card; symbol placement follows money()."""
    if abs(amount) < 10_000:
        return money(amount, currency)
    sample = money(1, currency)                    # 'MX$1.00' or '1.00 zł' or '¥1'
    num = "1.00" if "1.00" in sample else "1"
    return sample.replace(num, compact(amount), 1)


def _dominant_currency(games: list[Game]) -> str:
    """Currency shared by most priced games (falls back to USD)."""
    counts = Counter(g.price.currency for g in games if g.price and g.price.currency)
    return counts.most_common(1)[0][0] if counts else "USD"


class WishlistView(QWidget):
    """Grid of GameCards with filters, sort, stats and bulk actions."""

    def __init__(self, parent=None, on_add_game: Optional[Callable[[], None]] = None,
                 on_game_click: Optional[Callable[[Game], None]] = None, **deps):
        super().__init__(parent)
        self._on_add_game = on_add_game
        self._on_game_click = on_game_click
        self._notify_dep: Optional[Callable] = deps.get("notify")
        self._data_changed_dep: Optional[Callable] = deps.get("on_data_changed")

        self._games: list[Game] = []
        self._query = ""
        self._status = "all"
        self._priority = "any"
        self._sort = "priority"
        self._busy = False

        self._pending: deque[tuple[FlowLayout, Game]] = deque()
        self._generation = 0
        self._group_headers: dict[str, SubHeader] = {}

        self._build_timer = QTimer(self)          # chunked card construction
        self._build_timer.setInterval(0)
        self._build_timer.timeout.connect(self._build_chunk)
        self._search_timer = QTimer(self)         # search debounce
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE)
        self._search_timer.timeout.connect(self._render)

        self._build()
        QShortcut(QKeySequence.StandardKey.Find, self,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
                  activated=self._focus_search)

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["xl"]), SP["lg"])

        # header
        self._progress = QProgressBar()
        self._progress.setFixedWidth(140)
        self._progress.setTextVisible(False)
        self._progress.hide()
        self._refresh_btn = Button("", icon="refresh", on_click=self._refresh_prices)
        self._more_btn = IconButton("ellipsis", "", on_click=self._open_more_menu)
        self._add_btn = Button("", variant="primary", icon="plus", on_click=self._add_game)
        self._menu = QMenu(self)
        self._act_covers = self._menu.addAction(icons.icon("download", C["text"]), "", self._download_covers)
        self._act_export = self._menu.addAction(icons.icon("file-spreadsheet", C["text"]), "", self._export_excel)
        self._header = SectionHeader("", "", actions=[self._progress, self._refresh_btn, self._more_btn, self._add_btn])
        root.addWidget(self._header)

        # toolbar
        self._toolbar = QWidget()
        tb = vbox(self._toolbar, spacing=SP["sm"])
        row1 = hbox(spacing=SP["md"])
        self._search = SearchField("")
        self._search.setMinimumWidth(260)
        self._search.setMaximumWidth(380)
        self._search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._search.textChanged.connect(self._on_search)
        row1.addWidget(self._search, 3)
        self._status_seg = Segmented([(k, "") for k in STATUS_FILTERS], current="all")
        self._status_seg.changed.connect(self._on_status)
        row1.addWidget(self._status_seg)
        row1.addStretch(1)
        tb.addLayout(row1)

        row2 = hbox(spacing=SP["md"])
        self._prio_chips = ChipGroup([("any", "")] + [(p, p) for p in PRIORITIES], current="any")
        self._prio_chips.changed.connect(self._on_priority)
        row2.addWidget(self._prio_chips)
        row2.addStretch()
        self._sort_lbl = label("", "muted")
        row2.addWidget(self._sort_lbl)
        self._sort_combo = QComboBox()
        self._sort_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for k in SORTS:
            self._sort_combo.addItem("", k)
        self._sort_combo.currentIndexChanged.connect(self._on_sort)
        row2.addWidget(self._sort_combo)
        tb.addLayout(row2)
        root.addWidget(self._toolbar)

        # stats
        self._stats_row = QWidget()
        self._stats_grid = QGridLayout(self._stats_row)
        self._stats_grid.setContentsMargins(0, 0, 0, 0)
        self._stats_grid.setSpacing(SP["md"])
        self._st_total = StatCard("", "0", icon="heart", tone="accent")
        self._st_sale = StatCard("", "0", icon="tag", tone="green")
        self._st_value = StatCard("", "—", icon="wallet", tone="gold")
        self._st_low = StatCard("", "0", icon="medal", tone="violet")
        self._stat_cards = (self._st_total, self._st_sale, self._st_value, self._st_low)
        self._stat_cols = 0
        self._place_stats(4)
        root.addWidget(self._stats_row)

        # grid
        self._content = QWidget()
        self._content_lay = vbox(self._content, (0, 0, SP["sm"], 0), SP["sm"])
        self._content_lay.addStretch()
        self._scroll = scroll_area(self._content)
        root.addWidget(self._scroll, 1)

        # empty states
        self._empty_add_btn = Button("", variant="primary", icon="plus", on_click=self._add_game)
        self._empty = EmptyState("heart", "", "", action=self._empty_add_btn)
        self._empty.hide()
        root.addWidget(self._empty, 1)
        self._clear_btn = Button("", icon="x", on_click=self.clear_filters)
        self._no_match = EmptyState("search", "", "", action=self._clear_btn)
        self._no_match.hide()
        root.addWidget(self._no_match, 1)

        self.retranslate()

    def _place_stats(self, cols: int) -> None:
        """Lay the stat tiles out in `cols` columns (4 wide, 2 × 2 when narrow)."""
        if cols == self._stat_cols:
            return
        self._stat_cols = cols
        for card in self._stat_cards:
            self._stats_grid.removeWidget(card)
        for c in range(4):
            self._stats_grid.setColumnStretch(c, 1 if c < cols else 0)
        for i, card in enumerate(self._stat_cards):
            self._stats_grid.addWidget(card, i // cols, i % cols)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_stats(4 if event.size().width() >= _STATS_4COL_MIN else 2)

    # ── shell contract ───────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> None:
        """Reload games from the repository and re-render (force is a no-op here:
        nothing in this view is cached beyond the repository's own cache)."""
        self._games = repo.get_all()
        self._update_stats()
        self._render()

    def retranslate(self) -> None:
        t = i18n.t
        self._header.title.setText(t("nav.wishlist"))
        self._refresh_btn.setText(t("actions.refresh"))
        self._add_btn.setText(t("actions.add"))
        self._empty_add_btn.setText(t("actions.add"))
        self._more_btn.setToolTip(t("wishlist.more"))
        self._more_btn.setAccessibleName(t("wishlist.more"))
        self._act_covers.setText(t("wishlist.download_covers"))
        self._act_export.setText(t("actions.export"))
        self._search.setPlaceholderText(t("wishlist.search_placeholder"))
        for key, lk in (("all", "filters.all"), ("sa", "filters.priority_sa"),
                        ("sale", "filters.on_sale"), ("purchased", "filters.purchased")):
            self._status_seg.set_label(key, t(lk))
        self._prio_chips.set_label("any", t("wishlist.any_priority"))
        self._sort_lbl.setText(t("wishlist.sort_label"))
        for i, k in enumerate(SORTS):
            self._sort_combo.setItemText(i, t(f"wishlist.sort_{k}"))
        self._st_total.set_title(t("wishlist.stat_games"))
        self._st_sale.set_title(t("stats.on_sale_now"))
        self._st_value.set_title(t("wishlist.stat_value"))
        self._st_low.set_title(t("wishlist.stat_low"))
        self._empty.title.setText(t("wishlist.empty_title"))
        self._empty.subtitle.setText(t("wishlist.empty_subtitle"))
        self._empty.subtitle.setVisible(True)
        self._no_match.title.setText(t("wishlist.no_match_title"))
        self._no_match.subtitle.setText(t("wishlist.no_match_subtitle"))
        self._no_match.subtitle.setVisible(True)
        self._clear_btn.setText(t("wishlist.clear_filters"))
        for p, hdr in self._group_headers.items():
            hdr.title.setText(self._group_title(p))
        if self._games:
            self._update_stats(animate=False)
            self._update_subtitle(self._filtered())

    # ── filters ──────────────────────────────────────────────────────────────

    def clear_filters(self) -> None:
        """Reset search, status and priority filters (sort is kept)."""
        self._query = ""
        self._status = "all"
        self._priority = "any"
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._status_seg.set_current("all", emit=False)
        self._prio_chips.set_current("any", emit=False)
        self._render()

    def _focus_search(self) -> None:
        self._search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search.selectAll()

    def _on_search(self, text: str) -> None:
        self._query = text.strip().casefold()
        self._search_timer.start()

    def _on_status(self, key: str) -> None:
        self._status = key
        self._render()

    def _on_priority(self, key: str) -> None:
        self._priority = key
        self._render()

    def _on_sort(self, index: int) -> None:
        self._sort = self._sort_combo.itemData(index) or "priority"
        self._render()

    def _filtered(self) -> list[Game]:
        games = self._games
        if self._status == "purchased":
            games = [g for g in games if _is_purchased(g)]
        else:
            games = [g for g in games if not _is_purchased(g)]
            if self._status == "sa":
                games = [g for g in games if g.priority in ("S", "A")]
            elif self._status == "sale":
                games = [g for g in games if _on_sale(g)]
        if self._priority in PRIORITIES:
            games = [g for g in games if g.priority == self._priority]
        if self._query:
            q = self._query
            games = [g for g in games
                     if q in (g.name or "").casefold() or q in (g.developer or "").casefold()
                     or q in (g.genre or "").casefold()]
        return games

    def _sorted(self, games: list[Game]) -> list[Game]:
        s = self._sort
        if s == "name" or s == "priority":
            return sorted(games, key=lambda g: (g.name or "").casefold())
        if s == "price":
            return sorted(games, key=lambda g: (g.price is None, g.price.current if g.price else 0.0,
                                                (g.name or "").casefold()))
        if s == "discount":
            return sorted(games, key=lambda g: (-(g.price.discount_pct if _on_sale(g) else 0),
                                                (g.name or "").casefold()))
        if s == "added":
            return sorted(games, key=lambda g: (g.date_added or "", (g.name or "").casefold()), reverse=True)
        return games

    # ── render ───────────────────────────────────────────────────────────────

    def _render(self) -> None:
        """Rebuild the grid for the current filter; cards are created in chunks."""
        self._generation += 1
        self._pending.clear()
        self._build_timer.stop()
        self._group_headers.clear()
        # drop everything but the trailing stretch
        while self._content_lay.count() > 1:
            item = self._content_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                clear_layout(item.layout())

        has_games = bool(self._games)
        shown = self._sorted(self._filtered()) if has_games else []
        self._update_subtitle(shown)

        self._toolbar.setVisible(has_games)
        self._stats_row.setVisible(has_games)
        if not self._busy:
            self._refresh_btn.setEnabled(has_games)
        self._empty.setVisible(not has_games)
        self._no_match.setVisible(has_games and not shown)
        self._scroll.setVisible(bool(shown))
        if not shown:
            return

        if self._sort == "priority":
            for p in PRIORITIES:
                group = [g for g in shown if g.priority == p]
                if not group:
                    continue
                count = label(i18n.t("wishlist.games_one" if len(group) == 1 else "wishlist.games_other",
                                     n=len(group)), "muted")
                hdr = SubHeader(self._group_title(p), trailing=count)
                hdr.layout().insertWidget(0, PriorityBadge(p))
                self._group_headers[p] = hdr
                self._content_lay.insertWidget(self._content_lay.count() - 1, hdr)
                self._add_grid(group)
        else:
            self._add_grid(shown)
        self._build_chunk()
        if self._pending:
            self._build_timer.start()

    def _add_grid(self, games: list[Game]) -> None:
        host = QWidget()
        flow = FlowLayout(host, SP["md"], SP["md"])
        self._content_lay.insertWidget(self._content_lay.count() - 1, host)
        for g in games:
            self._pending.append((flow, g))

    def _build_chunk(self) -> None:
        gen = self._generation
        self._content.setUpdatesEnabled(False)
        try:
            for _ in range(_CHUNK):
                if not self._pending or gen != self._generation:
                    break
                flow, game = self._pending.popleft()
                flow.addWidget(GameCard(game, on_click=self._on_game_click))
        finally:
            self._content.setUpdatesEnabled(True)
        if not self._pending:
            self._build_timer.stop()

    def _group_title(self, p: str) -> str:
        raw = i18n.t(f"priority.{p}")
        return _PRIO_PREFIX.sub("", raw) or raw

    # ── stats ────────────────────────────────────────────────────────────────

    def _update_subtitle(self, shown: list[Game]) -> None:
        wish = [g for g in self._games if not _is_purchased(g)]
        n, sale = len(wish), sum(1 for g in wish if _on_sale(g))
        bits = []
        if self._games and len(shown) != n:
            bits.append(i18n.t("wishlist.showing", shown=len(shown), n=n))
        else:
            bits.append(i18n.t("wishlist.games_one" if n == 1 else "wishlist.games_other", n=n))
        if sale:
            bits.append(i18n.t("wishlist.on_sale_count", n=sale))
        self._header.subtitle.setText(" · ".join(bits))
        self._header.subtitle.setVisible(True)

    def _update_stats(self, animate: bool = True) -> None:
        wish = [g for g in self._games if not _is_purchased(g)]
        purchased = len(self._games) - len(wish)
        cur = _dominant_currency(wish)
        priced = [g for g in wish if g.price is not None and g.price.currency == cur]
        on_sale = sum(1 for g in wish if _on_sale(g))
        total_value = sum(g.price.current for g in priced)
        savings = sum(max(0.0, g.price.base - g.price.current) for g in priced if _on_sale(g))
        at_low = sum(1 for g in wish if _at_low(g))
        t = i18n.t

        self._st_total.set_value(len(wish), animate=animate)
        self._st_total.set_caption(t("wishlist.purchased_caption", n=purchased))
        self._st_sale.set_value(on_sale, animate=animate)
        self._st_sale.set_caption(t("wishlist.sale_caption", pct=pct(100 * on_sale / len(wish))) if wish else "")
        self._st_value.set_value(total_value, fmt=lambda v: _money_fit(v, cur), animate=animate)
        self._st_value.set_caption(t("wishlist.value_caption", saved=money(savings, cur)) if savings > 0
                                   else t("wishlist.no_savings"))
        self._st_low.set_value(at_low, animate=animate)
        self._st_low.set_caption(t("wishlist.low_caption"))

    # ── actions ──────────────────────────────────────────────────────────────

    def _add_game(self) -> None:
        if self._on_add_game:
            self._on_add_game()

    def _open_more_menu(self) -> None:
        self._menu.exec(self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft()))

    def _notify(self, message: str, tone: str = "info") -> None:
        fn = self._notify_dep or getattr(self.window(), "notify", None)
        if fn:
            fn(message, tone)

    def _data_changed(self) -> None:
        fn = self._data_changed_dep or getattr(self.window(), "on_data_changed", None)
        if fn:
            fn()
        else:
            self.refresh(force=True)

    def _set_busy(self, busy: bool, text: Optional[str] = None) -> None:
        self._busy = busy
        self._refresh_btn.set_loading(busy, text)
        self._more_btn.setEnabled(not busy)
        self._progress.setVisible(busy)
        if busy:
            self._progress.setRange(0, 0)

    def _on_progress(self, step: tuple) -> None:
        cur, total, key = step
        if total:
            self._progress.setRange(0, total)
            self._progress.setValue(cur)
        self._refresh_btn.setText(i18n.t(key, cur=cur, total=total))

    def _refresh_prices(self) -> None:
        """Bulk price refresh through run_async; bulk_refresh_prices spawns its
        own workers and reports via callbacks, so the job waits for on_done."""
        if self._busy:
            return
        from services.steam_api import bulk_refresh_prices
        from ui.settings_loader import get_settings
        games = repo.get_all()
        if not games:
            return
        country = get_settings().get("country", "us")
        self._set_busy(True, i18n.t("wishlist.refreshing", cur=0, total=len(games)))

        def work(progress):
            done = threading.Event()
            box: dict = {}

            def _done(updated, unchanged, failed):
                box["r"] = (updated, unchanged, failed)
                done.set()

            bulk_refresh_prices(games, country=country,
                                on_progress=lambda c, t, _n: progress((c, t, "wishlist.refreshing")),
                                on_done=_done, max_workers=6)
            done.wait()
            return box["r"]

        def on_done(result):
            self._set_busy(False)
            if isinstance(result, Exception):
                self._notify(i18n.t("wishlist.refresh_failed", msg=str(result)), "error")
                return
            updated, _unchanged, failed = result
            if failed:
                self._notify(i18n.t("wishlist.refresh_done_errors", n=updated, fail=failed), "warning")
            else:
                self._notify(i18n.t("wishlist.refresh_done", n=updated), "success")
            self._data_changed()

        run_async(self, work, on_done=on_done, on_progress=self._on_progress)

    def _download_covers(self) -> None:
        if self._busy:
            return
        from services.steamgriddb import cover_exists, download_all_missing
        from ui.settings_loader import get_settings
        games = repo.get_all()
        missing = sum(1 for g in games if not cover_exists(g.app_id))
        if missing == 0:
            self._notify(i18n.t("wishlist.covers_none"), "info")
            return
        api_key = get_settings().get("steamgriddb_key", "") or ""
        self._set_busy(True, i18n.t("wishlist.covers_progress", cur=0, total=missing))

        def work(progress):
            done = threading.Event()
            box: dict = {}

            def _done(downloaded, failed):
                box["r"] = (downloaded, failed)
                done.set()

            download_all_missing(games, api_key,
                                 on_progress=lambda c, t, _n: progress((c, t, "wishlist.covers_progress")),
                                 on_done=_done, max_workers=4)
            done.wait()
            return box["r"]

        def on_done(result):
            self._set_busy(False)
            if isinstance(result, Exception):
                self._notify(i18n.t("wishlist.covers_failed", msg=str(result)), "error")
                return
            downloaded, failed = result
            from ui import image_cache
            image_cache.clear()
            if failed:
                self._notify(i18n.t("wishlist.covers_done_errors", n=downloaded, fail=failed), "warning")
            else:
                self._notify(i18n.t("wishlist.covers_done", n=downloaded), "success")
            self._data_changed()

        run_async(self, work, on_done=on_done, on_progress=self._on_progress)

    def _export_excel(self) -> None:
        from data.excel_manager import export_excel

        def on_done(result):
            if isinstance(result, Exception):
                self._notify(i18n.t("wishlist.export_failed", msg=str(result)), "error")
            else:
                self._notify(i18n.t("wishlist.export_done", path=str(result)), "success")

        run_async(self, export_excel, on_done=on_done)
