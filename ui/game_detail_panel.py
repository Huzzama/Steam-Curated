"""
GameDetailPanel — the 340 px slide-in panel on the right of the shell.

    panel = GameDetailPanel(parent, on_close=shell.close_detail, on_refresh=shell.on_data_changed)
    panel.load_game(game)      # show a game (regions are fetched once per app_id)
    panel.reload()             # re-read the game from the repository and re-render in place
    panel.retranslate()        # update visible strings after a locale change

The widget tree is built once; `_apply(game)` updates it in place so edits
(priority, rating, notes…) never rebuild the panel or reset the scroll.
Network work (price refresh, region comparison, cover download) goes through
`run_async`; the region table shows Skeleton rows meanwhile.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QPlainTextEdit, QWidget

import i18n
from config import PRIORITY_OPTIONS
from data import purchase_repository as purchases
from data import repository as repo
from data.models import Game, PriceInfo
from data.status import STATUS_ARCHIVED, STATUS_PURCHASED
from ui import icons, image_cache
from ui.animations import clear_layout
from services.price_history import merge as price_history_merge
from ui.async_bridge import run_async
from ui.components import (Button, Card, CoverImage, Divider, IconButton, Pill, Segmented,
                           Skeleton, hbox, label, scroll_area, vbox)
from ui.format import day, discount, money
from ui.settings_loader import get_settings
from ui.theme import C, SP

log = logging.getLogger("curator.detail")

PANEL_WIDTH = 340
COVER_W, COVER_H = 90, 135
_PLAY_STATUSES = ["", "playing", "completed", "on_hold", "abandoned"]
_MAX_RATING = 5

# Rough USD equivalents so regional prices can be ranked ("Cheapest") without
# a currency API. A "cheap vs expensive" signal only — never shown as money.
_USD_RATES = {
    "USD": 1.0, "MXN": 0.050, "BRL": 0.18, "JPY": 0.0065, "EUR": 1.08, "GBP": 1.27,
    "CAD": 0.73, "AUD": 0.64, "RUB": 0.011, "TRY": 0.028, "KRW": 0.00073, "CNY": 0.138,
    "PLN": 0.25, "CZK": 0.044, "HUF": 0.0027, "NOK": 0.094, "SEK": 0.095, "DKK": 0.145,
    "CHF": 1.12, "NZD": 0.60, "SGD": 0.74, "HKD": 0.128, "TWD": 0.031, "THB": 0.028,
    "INR": 0.012, "CLP": 0.00105, "COP": 0.00024, "PEN": 0.27, "ARS": 0.00095, "UAH": 0.024,
}

# recommendation verdict → (tone colour, icon, i18n key)
_VERDICT = {
    "buy_now":   (C["green"],    "badge-check", "recommendation.buy_now"),
    "good_deal": (C["accent"],   "tag",         "recommendation.good_deal"),
    "wait":      (C["gold"],     "hourglass",   "recommendation.wait"),
    "no_data":   (C["text_dim"], "info",        "recommendation.no_data"),
}
_VERDICT_TONE = {"buy_now": "green", "good_deal": "accent", "wait": "gold", "no_data": "neutral"}


def _icon_label(name: str, color: str, size: int = 14) -> QLabel:
    lbl = QLabel()
    lbl.setPixmap(icons.pixmap(name, color, size))
    lbl.setFixedSize(size, size)
    return lbl


def _to_usd(p: Optional[PriceInfo]) -> Optional[float]:
    if not p:
        return None
    rate = _USD_RATES.get((p.currency or "").upper())
    return None if rate is None else p.current * rate


class GameDetailPanel(QWidget):
    """Slide-in detail panel: cover · price · regions · editable fields · actions."""

    def __init__(self, parent=None, on_close: Optional[Callable] = None,
                 on_refresh: Optional[Callable] = None, **deps):
        super().__init__(parent)
        self._on_close = on_close or (lambda: None)
        self._on_refresh = on_refresh or (lambda: None)
        self._notify_dep: Optional[Callable] = deps.get("notify")
        self._game: Optional[Game] = None
        self._region_cache: dict[str, dict[str, Optional[PriceInfo]]] = {}
        self._region_order: list[str] = []
        self._refreshing = False
        self._hist_pending: set[str] = set()
        self.setFixedWidth(PANEL_WIDTH)
        self._build()
        self.retranslate()

    # ── build (once) ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = vbox(self, (0, 0, 0, 0), 0)

        # top bar
        top = QWidget()
        top.setFixedHeight(48)
        tl = hbox(top, (SP["lg"], 0, SP["sm"], 0), SP["xs"])
        self._eyebrow = label("", "eyebrow")
        tl.addWidget(self._eyebrow)
        tl.addStretch()
        self._refresh_btn = IconButton("refresh", on_click=self._refresh_price)
        tl.addWidget(self._refresh_btn)
        self._close_btn = IconButton("close", on_click=self._on_close)
        tl.addWidget(self._close_btn)
        root.addWidget(top)
        root.addWidget(Divider())

        content = QWidget()
        lay = vbox(content, (SP["lg"], SP["lg"], SP["md"], SP["xl"]), SP["lg"])
        self._scroll = scroll_area(content)
        root.addWidget(self._scroll, 1)

        # header: cover + name / meta / pills
        head = hbox(spacing=SP["md"])
        self._cover = CoverImage(COVER_W, COVER_H)
        head.addWidget(self._cover, 0, Qt.AlignmentFlag.AlignTop)
        col = vbox(spacing=SP["xs"])
        self._name = label("", "title", wrap=True)
        self._name.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        col.addWidget(self._name)
        self._meta = label("", "muted", wrap=True)
        col.addWidget(self._meta)
        col.addSpacing(SP["xs"])
        pills = hbox(spacing=SP["xs"])
        self._status_pill = Pill("", "neutral", mono=False)
        self._play_pill = Pill("", "accent", mono=False)
        self._low_pill = Pill("", "gold")
        for p in (self._status_pill, self._play_pill, self._low_pill):
            pills.addWidget(p)
        pills.addStretch()
        col.addLayout(pills)
        col.addStretch()
        head.addLayout(col, 1)
        lay.addLayout(head)
        lay.addWidget(Divider())

        # price
        self._price_title = self._section(lay, "detail.price_section")
        prow = hbox(spacing=SP["sm"])
        # two labels (normal / on-sale green) so no stylesheet is touched at runtime
        self._price_value = label("", "value")
        prow.addWidget(self._price_value, 0, Qt.AlignmentFlag.AlignBottom)
        self._price_value_sale = label("", "value", color=C["green"])
        prow.addWidget(self._price_value_sale, 0, Qt.AlignmentFlag.AlignBottom)
        self._price_base = label("", "muted")
        self._price_base.setProperty("role", "mono")
        prow.addWidget(self._price_base, 0, Qt.AlignmentFlag.AlignBottom)
        self._disc_pill = Pill("", "green")
        prow.addWidget(self._disc_pill, 0, Qt.AlignmentFlag.AlignBottom)
        prow.addStretch()
        lay.addLayout(prow)

        self._low_row = QWidget()
        lrow = hbox(self._low_row, spacing=SP["sm"])
        lrow.addWidget(_icon_label("chart-line", C["accent"]))
        self._low_label = label("", "dim")
        lrow.addWidget(self._low_label)
        lrow.addStretch()
        self._low_value = label("", "mono", weight=QFont.Weight.Bold)
        lrow.addWidget(self._low_value)
        self._low_date = label("", "muted")
        lrow.addWidget(self._low_date)
        lay.addWidget(self._low_row)

        self._hint_row = QWidget()
        hrow = hbox(self._hint_row, spacing=SP["sm"])
        hrow.addWidget(_icon_label("key-round", C["text_muted"]), 0, Qt.AlignmentFlag.AlignTop)
        self._hint = label("", "muted", wrap=True)
        hrow.addWidget(self._hint, 1)
        lay.addWidget(self._hint_row)

        self._rec_card = Card(padding=SP["md"], spacing=SP["sm"])
        lay.addWidget(self._rec_card)
        lay.addWidget(Divider())

        # regions
        self._regions_title = self._section(lay, "detail.price_by_region")
        self._region_card = Card(padding=SP["md"], spacing=0)
        lay.addWidget(self._region_card)
        lay.addWidget(Divider())

        # editable fields
        self._take_title = self._section(lay, "detail.your_take")
        self._priority_label = label("", "dim")
        self._priority = Segmented([(p, p) for p in PRIORITY_OPTIONS])
        self._priority.changed.connect(self._on_priority)
        lay.addLayout(self._field(self._priority_label, self._priority))

        self._play_label = label("", "dim")
        self._play = QComboBox()
        self._play.setMinimumHeight(34)
        for key in _PLAY_STATUSES:
            self._play.addItem("", key)
        self._play.currentIndexChanged.connect(self._on_play_status)
        lay.addLayout(self._field(self._play_label, self._play))

        self._rating_label = label("", "dim")
        stars_box = QWidget()
        stars = hbox(stars_box, (0, 0, 0, 0), SP["xs"])
        self._stars: list[IconButton] = []
        for i in range(1, _MAX_RATING + 1):
            b = IconButton("star", size=20, color=C["text_muted"],
                           on_click=lambda _=False, n=i: self._on_rating(n))
            self._stars.append(b)
            stars.addWidget(b)
        stars.addStretch()
        lay.addLayout(self._field(self._rating_label, stars_box))

        self._notes_label = label("", "dim")
        self._notes = QPlainTextEdit()
        self._notes.setFixedHeight(84)
        self._notes.installEventFilter(self)
        lay.addLayout(self._field(self._notes_label, self._notes))
        srow = hbox()
        srow.addStretch()
        self._save_btn = Button("", "link", icon="check", on_click=self._save_notes)
        srow.addWidget(self._save_btn)
        lay.addLayout(srow)
        lay.addWidget(Divider())

        # actions
        self._purchased_card = Card(padding=SP["md"], spacing=2)
        self._purchased_card.setProperty("surface", "inset")
        pc = hbox(spacing=SP["sm"])
        pc.addWidget(_icon_label("badge-check", C["green"], 16), 0, Qt.AlignmentFlag.AlignTop)
        pcol = vbox(spacing=2)
        self._purchased_title = label("", "body", color=C["green"], wrap=True)
        pcol.addWidget(self._purchased_title)
        self._purchased_sub = label("", "muted")
        self._purchased_sub.setProperty("role", "mono")
        pcol.addWidget(self._purchased_sub)
        pc.addLayout(pcol, 1)
        self._purchased_card.body.addLayout(pc)
        lay.addWidget(self._purchased_card)

        self._buy_btn = Button("", "primary", icon="shopping-cart", on_click=self._mark_purchased)
        self._buy_btn.setMinimumHeight(36)
        lay.addWidget(self._buy_btn)
        self._steam_btn = Button("", "default", icon="external", on_click=self._open_steam)
        lay.addWidget(self._steam_btn)
        self._cover_btn = Button("", "ghost", icon="image", on_click=self._download_cover)
        lay.addWidget(self._cover_btn)
        self._delete_btn = Button("", "danger", icon="trash", on_click=self._delete)
        lay.addWidget(self._delete_btn)
        lay.addStretch()

    @staticmethod
    def _field(title: QLabel, widget: QWidget):
        """Label + input grouped tightly (xs) so the lg section spacing reads as groups."""
        col = vbox(spacing=SP["xs"])
        col.addWidget(title)
        col.addWidget(widget)
        return col

    def _section(self, lay, key: str) -> QLabel:
        """Uppercase eyebrow title for a section; returns the label for retranslate."""
        lbl = label("", "eyebrow")
        lbl.setProperty("i18n", key)
        lay.addWidget(lbl)
        return lbl

    # ── public API ───────────────────────────────────────────────────────────

    def load_game(self, game: Game) -> None:
        """Show *game*; region prices are fetched once per app_id."""
        self._game = game
        self._apply(game)
        self._scroll.verticalScrollBar().setValue(0)
        self._load_regions(game)
        self._ensure_history(game)

    def _ensure_history(self, g: Game) -> None:
        """Fetch the all-time low in the background when the game has none yet
        (ITAD if a key is set, otherwise the locally observed low)."""
        app_id = str(g.app_id or "")
        if not app_id or app_id.startswith("unknown") or g.price_history is not None:
            return
        if app_id in self._hist_pending:
            return
        self._hist_pending.add(app_id)
        country = get_settings().get("country") or "us"
        currency = g.price.currency if g.price else None

        def work():
            from services import price_history
            return price_history.get_price_history(app_id, country, currency=currency)

        def on_done(result):
            self._hist_pending.discard(app_id)
            if isinstance(result, Exception) or result is None:
                return
            if self._game is None or str(self._game.app_id) != app_id:
                target = repo.get_by_app_id(app_id)
                if target is not None and target.price_history is None:
                    target.price_history = result
                    repo.update(target)
                return
            self._game.price_history = result
            repo.update(self._game)
            self._apply(self._game)
            self._on_refresh()

        run_async(self, work, on_done=on_done)

    def reload(self) -> None:
        """Re-read the current game from the repository and re-render in place."""
        if self._game is None:
            return
        fresh = repo.get_by_id(self._game.id)
        if fresh is None:            # deleted elsewhere
            return
        self._game = fresh
        self._apply(fresh)
        if fresh.app_id in self._region_cache:
            self._render_regions(self._region_cache[fresh.app_id])

    def retranslate(self) -> None:
        t = i18n.t
        self._eyebrow.setText(t("detail.eyebrow").upper())
        self._refresh_btn.setToolTip(t("detail.refresh"))
        self._close_btn.setToolTip(t("detail.close"))
        for lbl in (self._price_title, self._regions_title, self._take_title):
            lbl.setText(t(lbl.property("i18n")).upper())
        self._low_label.setText(t("game.price_low"))
        self._priority_label.setText(t("game.priority"))
        self._play_label.setText(t("detail.play_status"))
        self._rating_label.setText(t("game.rating"))
        self._notes_label.setText(t("game.notes"))
        self._notes.setPlaceholderText(t("detail.notes_placeholder"))
        self._save_btn.setText(t("actions.save"))
        self._buy_btn.setText(t("detail.mark_purchased"))
        self._steam_btn.setText(t("detail.open_steam"))
        self._cover_btn.setText(t("detail.download_cover"))
        self._delete_btn.setText(t("detail.delete_game"))
        self._low_pill.setText(t("game.at_low").upper())
        for i, key in enumerate(_PLAY_STATUSES):
            self._play.setItemText(i, t(f"play_status.{key or 'none'}"))
        for p in PRIORITY_OPTIONS:
            self._priority.set_label(p, p)
        if self._game is not None:
            self._apply(self._game)
            if self._game.app_id in self._region_cache:
                self._render_regions(self._region_cache[self._game.app_id])

    # ── render in place ──────────────────────────────────────────────────────

    def _apply(self, g: Game) -> None:
        t = i18n.t
        self._cover.set_pixmap(image_cache.get(g.cover_path, (COVER_W, COVER_H)))
        self._name.setText(g.name)
        meta = [g.genre, str(g.release_year) if g.release_year else "", g.developer]
        self._meta.setText(" · ".join(m for m in meta if m))
        self._meta.setVisible(bool(self._meta.text()))

        # pills
        if g.status == STATUS_PURCHASED:
            self._status_pill.setText(t("mark_purchased.purchased_badge")); self._status_pill.set_tone("green")
        elif g.status == STATUS_ARCHIVED:
            self._status_pill.setText(t("status.Archivado")); self._status_pill.set_tone("neutral")
        else:
            self._status_pill.setText(t("status.Wishlist")); self._status_pill.set_tone("neutral")
        self._play_pill.setText(t(f"play_status.{g.play_status}") if g.play_status else "")
        self._play_pill.setVisible(bool(g.play_status))
        diff = g.price_diff_pct
        self._low_pill.setVisible(diff is not None and diff <= 5)

        # price
        p = g.price
        sale = bool(p and p.is_on_sale)
        self._price_value.setVisible(not sale)
        self._price_value_sale.setVisible(sale)
        if p:
            (self._price_value_sale if sale else self._price_value).setText(money(p.current, p.currency))
            struck = bool(sale and p.base and p.base > p.current)
            self._price_base.setText(f"<s>{money(p.base, p.currency)}</s>" if struck else "")
            self._price_base.setVisible(struck)
            self._disc_pill.setText(discount(p.discount_pct))
            self._disc_pill.setVisible(bool(p.discount_pct))
        else:
            self._price_value.setText(money(None))
            self._price_base.setVisible(False)
            self._disc_pill.setVisible(False)

        from services import price_history
        h = g.price_history
        has_low = bool(h and h.all_time_low and h.all_time_low > 0)
        self._low_row.setVisible(has_low)
        if has_low:
            cur = p.currency if p else "USD"
            self._low_value.setText(money(h.all_time_low, cur))
            src = getattr(h, "source", "") or ""
            date_txt = day(h.all_time_low_date) if h.all_time_low_date else ""
            if src == price_history.SOURCE_OBSERVED:
                date_txt = t("detail.low_observed", date=date_txt) if date_txt else t("detail.low_observed_nodate")
            elif src == price_history.SOURCE_ITAD:
                date_txt = f"{date_txt} · ITAD" if date_txt else "ITAD"
            self._low_date.setText(date_txt)
            self._low_date.setVisible(bool(date_txt))
        configured = price_history.is_configured()
        self._hint_row.setVisible(not has_low or (not configured and getattr(h, "source", "") == price_history.SOURCE_OBSERVED))
        self._hint.setText(t("detail.no_history_refresh") if configured else t("detail.itad_hint"))

        self._render_recommendation(g)

        # editable fields (no signals while syncing)
        self._priority.set_current(g.priority if g.priority in PRIORITY_OPTIONS else None, emit=False)
        self._play.blockSignals(True)
        idx = _PLAY_STATUSES.index(g.play_status) if g.play_status in _PLAY_STATUSES else 0
        self._play.setCurrentIndex(idx)
        self._play.blockSignals(False)
        self._paint_stars(g.personal_rating or 0)
        if not self._notes.hasFocus() and self._notes.toPlainText() != (g.notes or ""):
            self._notes.setPlainText(g.notes or "")

        # actions
        bought = purchases.get_by_app_id(g.app_id) if g.app_id else None
        self._purchased_card.setVisible(bought is not None)
        self._buy_btn.setVisible(bought is None)
        if bought is not None:
            self._purchased_title.setText(
                t("detail.purchased_label", edition=bought.edition or t("detail.standard_edition")))
            self._purchased_sub.setText(t("detail.purchased_on",
                                          price=money(bought.price_paid, bought.currency),
                                          date=day(bought.purchased_at)))
        self._steam_btn.setVisible(bool(g.app_id or g.steam_url))
        self._cover_btn.setVisible(not g.cover_path and bool(g.app_id))

    def _render_recommendation(self, g: Game) -> None:
        clear_layout(self._rec_card.body)
        try:
            from services.recommendation import get_recommendation
            rec = get_recommendation(g)
        except Exception:  # noqa: BLE001
            log.exception("recommendation failed")
            self._rec_card.hide()
            return
        self._rec_card.show()
        verdict = rec.get("verdict", "no_data")
        color, icon, key = _VERDICT.get(verdict, _VERDICT["no_data"])
        body = self._rec_card.body
        head = hbox(spacing=SP["sm"])
        head.addWidget(_icon_label(icon, color, 16))
        head.addWidget(Pill(i18n.t(key).upper(), _VERDICT_TONE.get(verdict, "neutral")))
        head.addStretch()
        conf = rec.get("confidence")
        if conf and verdict != "no_data":
            head.addWidget(label(i18n.t(f"detail.confidence_{conf}").upper(), "eyebrow"))
        body.addLayout(head)
        body.addWidget(label(rec.get("headline", ""), "body", weight=QFont.Weight.Medium, wrap=True))
        if rec.get("reason"):
            body.addWidget(label(rec["reason"], "muted", wrap=True))
        if rec.get("next_sale"):
            inset = Card(padding=SP["sm"], spacing=2)
            inset.setProperty("surface", "inset")
            inset.body.addWidget(label(i18n.t("detail.next_sale").upper(), "eyebrow"))
            row = hbox(spacing=SP["sm"])
            row.addWidget(label(rec["next_sale"], "body", weight=QFont.Weight.Medium, wrap=True), 1)
            est = rec.get("est_price")
            if est is not None and g.price:
                row.addWidget(label(i18n.t("detail.est_price", price=money(est, g.price.currency)),
                                    "muted"), 0, Qt.AlignmentFlag.AlignTop)
            inset.body.addLayout(row)
            body.addWidget(inset)

    def _paint_stars(self, n: int) -> None:
        for i, b in enumerate(self._stars, start=1):
            b.set_icon("star", C["gold"] if i <= n else C["text_muted"])

    # ── regions ──────────────────────────────────────────────────────────────

    def _regions_for(self) -> list[str]:
        s = get_settings()
        base = (s.get("country") or "us").lower()
        extra = [str(c).lower() for c in (s.get("compare_regions") or [])]
        out = [base]
        for c in extra:
            if c and c not in out:
                out.append(c)
        return out

    def _load_regions(self, game: Game, force: bool = False) -> None:
        self._region_order = self._regions_for()
        app_id = str(game.app_id or "")
        if not app_id:
            self._render_regions({})
            return
        if not force and app_id in self._region_cache:
            self._render_regions(self._region_cache[app_id])
            return
        self._render_region_skeleton()
        regions = list(self._region_order)

        def work():
            from services import steam_api
            out: dict[str, Optional[PriceInfo]] = {}
            for cc in regions:
                try:
                    data = steam_api.get_app_details(app_id, cc, force=force)
                    out[cc] = steam_api.parse_price(data) if data else None
                except Exception as e:  # noqa: BLE001
                    log.warning("region %s: %s", cc, e)
                    out[cc] = None
            return out

        def on_done(result):
            if isinstance(result, Exception):
                result = {}
            self._region_cache[app_id] = result
            if self._game is not None and str(self._game.app_id) == app_id:
                self._render_regions(result)

        run_async(self, work, on_done=on_done)

    def _render_region_skeleton(self) -> None:
        body = self._region_card.body
        clear_layout(body)
        for i, cc in enumerate(self._region_order):
            if i:
                body.addWidget(Divider())
            row = hbox(margins=(0, SP["sm"], 0, SP["sm"]), spacing=SP["sm"])
            row.addWidget(Skeleton(96, 12))
            row.addStretch()
            row.addWidget(Skeleton(64, 12))
            body.addLayout(row)
        self._region_card.setVisible(bool(self._region_order))

    def _render_regions(self, prices: dict[str, Optional[PriceInfo]]) -> None:
        body = self._region_card.body
        clear_layout(body)
        self._region_card.show()
        t = i18n.t
        regions = self._region_order
        if not regions:
            body.addWidget(label(t("detail.regions_none"), "muted", wrap=True))
            return
        if not self._game or not self._game.app_id:
            body.addWidget(label(t("detail.no_app_id"), "muted", wrap=True))
            return
        if not any(prices.get(cc) for cc in regions):
            row = hbox(spacing=SP["sm"])
            row.addWidget(_icon_label("cloud-off", C["text_muted"]))
            row.addWidget(label(t("detail.regions_error"), "muted", wrap=True), 1)
            row.addWidget(Button(t("detail.retry"), "link", icon="refresh",
                                 on_click=lambda: self._load_regions(self._game, force=True)))
            body.addLayout(row)
            return

        usd = {cc: _to_usd(prices.get(cc)) for cc in regions}
        ranked = [cc for cc in regions if usd[cc] is not None]
        cheapest = min(ranked, key=lambda cc: usd[cc]) if len(ranked) > 1 else None
        base_cc = regions[0]
        for i, cc in enumerate(regions):
            if i:
                body.addWidget(Divider())
            p = prices.get(cc)
            row = hbox(margins=(0, SP["sm"], 0, SP["sm"]), spacing=SP["sm"])
            rn = t(f"regions.{cc}")
            row.addWidget(label(rn if rn != f"regions.{cc}" else cc.upper(), "body"))
            if cc == base_cc:
                row.addWidget(Pill(t("detail.base_ref").upper(), "neutral"))
            if cc == cheapest:
                row.addWidget(Pill(t("detail.cheapest").upper(), "green"))
            row.addStretch()
            if p:
                if p.discount_pct:
                    row.addWidget(Pill(discount(p.discount_pct), "green"))
                price = label(money(p.current, p.currency), "mono", weight=QFont.Weight.Bold,
                              color=C["green"] if p.is_on_sale else C["text"])
            else:
                price = label(t("detail.not_available"), "muted")
            row.addWidget(price)
            body.addLayout(row)

    # ── edits ────────────────────────────────────────────────────────────────

    def _save(self, ok_msg: Optional[str] = None) -> None:
        if self._game is None:
            return
        repo.update(self._game)
        if ok_msg:
            self._notify(ok_msg, "success")
        self._on_refresh()

    def _on_priority(self, p: str) -> None:
        if self._game and p != self._game.priority:
            self._game.priority = p
            self._save()

    def _on_play_status(self, idx: int) -> None:
        if self._game is None:
            return
        key = _PLAY_STATUSES[idx] if 0 <= idx < len(_PLAY_STATUSES) else ""
        if key != (self._game.play_status or ""):
            self._game.play_status = key
            self._save()

    def _on_rating(self, n: int) -> None:
        if self._game is None:
            return
        new = None if self._game.personal_rating == n else n     # click again to clear
        self._game.personal_rating = new
        self._paint_stars(new or 0)
        self._save()

    def _save_notes(self) -> None:
        if self._game is None:
            return
        text = self._notes.toPlainText().strip()
        if text != (self._game.notes or ""):
            self._game.notes = text
            self._save(i18n.t("detail.saved"))

    def eventFilter(self, obj, ev):
        if obj is self._notes and ev.type() == QEvent.Type.FocusOut:
            self._save_notes()
        return super().eventFilter(obj, ev)

    # ── actions ──────────────────────────────────────────────────────────────

    def _refresh_price(self) -> None:
        g = self._game
        if g is None or self._refreshing:
            return
        if not g.app_id:
            self._notify(i18n.t("detail.no_app_id"), "warning")
            return
        self._refreshing = True
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.set_icon("loader-circle", C["accent"])
        app_id, country = str(g.app_id), (get_settings().get("country") or "us")

        def work():
            from services import price_history, steam_api
            price = steam_api.refresh_price(app_id, country, force=True)
            hist = price_history.get_price_history(app_id, country, force=True,
                                                   currency=price.currency if price else None)
            return price, hist

        def on_done(result):
            self._refreshing = False
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.set_icon("refresh")
            if isinstance(result, Exception):
                self._notify(i18n.t("detail.refresh_failed", msg=str(result)), "error")
                return
            price, hist = result
            if self._game is None or str(self._game.app_id) != app_id:
                return
            if price:
                self._game.price = price
            if hist:
                self._game.price_history = price_history_merge(self._game.price_history, hist)
            if not price and not hist:
                self._notify(i18n.t("detail.refresh_failed", msg=i18n.t("detail.not_available")), "error")
                return
            repo.update(self._game)
            self._region_cache.pop(app_id, None)
            self._apply(self._game)
            self._load_regions(self._game, force=True)
            self._notify(i18n.t("detail.refreshed"), "success")
            self._on_refresh()

        run_async(self, work, on_done=on_done)

    def _download_cover(self) -> None:
        g = self._game
        if g is None or not g.app_id:
            return
        self._cover_btn.set_loading(True)
        app_id, name = str(g.app_id), g.name
        key = get_settings().get("steamgriddb_key", "") or ""

        def work():
            from services import steamgriddb
            return steamgriddb.download_cover(app_id, key, name)

        def on_done(result):
            self._cover_btn.set_loading(False)
            if isinstance(result, Exception) or not result:
                self._notify(i18n.t("detail.cover_failed"), "warning")
                return
            if self._game is None or str(self._game.app_id) != app_id:
                return
            image_cache.invalidate(app_id)
            self._game.cover_path = result
            repo.update(self._game)
            self._apply(self._game)
            self._notify(i18n.t("detail.cover_done"), "success")
            self._on_refresh()

        run_async(self, work, on_done=on_done)

    def _open_steam(self) -> None:
        g = self._game
        if g is None:
            return
        opened = bool(g.app_id) and QDesktopServices.openUrl(QUrl(f"steam://store/{g.app_id}"))
        if not opened:
            url = g.steam_url or (f"https://store.steampowered.com/app/{g.app_id}" if g.app_id else "")
            if url:
                QDesktopServices.openUrl(QUrl(url))

    def _mark_purchased(self) -> None:
        g = self._game
        if g is None:
            return
        from ui.mark_purchased_dialog import MarkPurchasedDialog

        def done(*_):
            self._on_refresh()
            self.reload()

        MarkPurchasedDialog(self.window(), g, on_success=done).exec()

    def _delete(self) -> None:
        g = self._game
        if g is None:
            return
        ans = QMessageBox.question(self, i18n.t("detail.delete_title"),
                                   i18n.t("detail.delete_body", name=g.name))
        if ans != QMessageBox.StandardButton.Yes:
            return
        repo.delete(g.id)
        self._game = None
        self._on_refresh()
        self._on_close()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _notify(self, message: str, tone: str = "info") -> None:
        fn = self._notify_dep or getattr(self.window(), "notify", None)
        if fn:
            try:
                fn(message, tone)
                return
            except Exception:  # noqa: BLE001
                pass
        log.info("%s: %s", tone, message)
