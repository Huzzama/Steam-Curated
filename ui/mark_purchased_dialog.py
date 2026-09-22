"""
MarkPurchasedDialog — record a purchase for a wishlist game.

    MarkPurchasedDialog(parent_window, game, on_success=cb).exec()

Tabs: Individual (free-form price) · Editions · Bundles (both fetched from
Steam through `run_async`, each row fills the form when clicked). Confirm
validates the numbers, writes a `Purchase`, flips the game to
`STATUS_PURCHASED`, reports the saving in the background and then calls
`on_success(purchase)` (falls back to `on_success()` for old callers).
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDateEdit, QDialog, QLabel, QStackedWidget, QWidget

import i18n
from data import purchase_repository as purchases
from data import repository as repo
from data.models import Game, Purchase
from data.status import STATUS_PURCHASED
from ui import animations, icons, image_cache
from ui.animations import clear_layout
from ui.async_bridge import run_async
from ui.components import (Button, CoverImage, Divider, EmptyState, ListRow, Pill, Segmented,
                           Skeleton, TextField, hbox, label, scroll_area, vbox)
from ui.format import discount, money, pct
from ui.settings_loader import get_settings
from ui.theme import C, SP

log = logging.getLogger("curator.purchase")

DIALOG_WIDTH = 520
LIST_HEIGHT = 212
COVER_W, COVER_H = 56, 84


def _num(text: str) -> Optional[float]:
    """'1,234.50' → 1234.5 · '' → None · garbage → None."""
    s = (text or "").strip().replace(",", "").replace("%", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


class MarkPurchasedDialog(QDialog):
    """Purchase form with Individual / Editions / Bundles sources."""

    def __init__(self, parent, game: Game, on_success: Optional[Callable] = None, **kwargs):
        super().__init__(parent)
        self._game = game
        self._on_success = on_success
        self._tab = "individual"
        self._items: dict[str, Optional[list[dict]]] = {"editions": None, "bundles": None}
        self._loading: set[str] = set()
        self._selected: Optional[dict] = None
        self._rows: dict[str, list[tuple[ListRow, QLabel]]] = {"editions": [], "bundles": []}
        self._saving = False

        self.setWindowTitle(i18n.t("mark_purchased.title"))
        self.setFixedWidth(DIALOG_WIDTH)
        self.setModal(True)
        self._build()
        self._fill_from_game()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        t = i18n.t
        lay = vbox(self, (SP["xl"], SP["xl"], SP["xl"], SP["xl"]), SP["lg"])

        # header
        head = hbox(spacing=SP["md"])
        cover = CoverImage(COVER_W, COVER_H)
        cover.set_pixmap(image_cache.get(self._game.cover_path, (COVER_W, COVER_H)))
        head.addWidget(cover, 0, Qt.AlignmentFlag.AlignTop)
        col = vbox(spacing=SP["xs"])
        col.addWidget(label(t("mark_purchased.title").upper(), "eyebrow"))
        col.addWidget(label(self._game.name, "title", wrap=True))
        p = self._game.price
        sub = hbox(spacing=SP["sm"])
        sub.addWidget(label(t("mark_purchased.subtitle", price=money(p.current, p.currency))
                            if p else t("mark_purchased.subtitle_no_price"), "dim"))
        if p and p.discount_pct:
            sub.addWidget(Pill(discount(p.discount_pct), "green"))
        sub.addStretch()
        col.addLayout(sub)
        col.addStretch()
        head.addLayout(col, 1)
        lay.addLayout(head)

        # tabs
        self._tabs = Segmented([("individual", t("mark_purchased.tab_individual")),
                                ("editions", t("mark_purchased.tab_editions")),
                                ("bundles", t("mark_purchased.tab_bundles"))], current="individual")
        self._tabs.changed.connect(self._set_tab)
        lay.addWidget(self._tabs)

        # list area (editions / bundles) — hidden on the Individual tab
        self._list_stack = QStackedWidget()
        self._list_stack.setFixedHeight(LIST_HEIGHT)
        self._list_pages: dict[str, QWidget] = {}
        self._list_lays = {}
        for key in ("editions", "bundles"):
            content = QWidget()
            self._list_lays[key] = vbox(content, (0, 0, SP["xs"], 0), SP["sm"])
            self._list_lays[key].addStretch()
            page = scroll_area(content)
            self._list_pages[key] = page
            self._list_stack.addWidget(page)
        self._list_stack.hide()
        lay.addWidget(self._list_stack)

        # form
        grid = vbox(spacing=SP["md"])
        r1 = hbox(spacing=SP["md"])
        self._price = TextField("0.00")
        self._price.textChanged.connect(self._recalc)
        r1.addLayout(self._field(t("mark_purchased.price_paid"), self._price), 3)
        self._currency = TextField("USD")
        self._currency.setMaxLength(3)
        self._currency.textChanged.connect(self._recalc)
        r1.addLayout(self._field(t("mark_purchased.currency"), self._currency), 1)
        grid.addLayout(r1)

        r2 = hbox(spacing=SP["md"])
        self._base = TextField("0.00")
        self._base.textChanged.connect(self._recalc)
        r2.addLayout(self._field(t("mark_purchased.base_price"), self._base), 3)
        disc_box = QWidget()
        disc_box.setMinimumHeight(34)
        dl = hbox(disc_box, (0, 0, 0, 0), SP["sm"])
        self._disc_pill = Pill("—", "neutral")
        dl.addWidget(self._disc_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        dl.addStretch()
        r2.addLayout(self._field(t("mark_purchased.discount"), disc_box), 1)
        grid.addLayout(r2)

        r3 = hbox(spacing=SP["md"])
        self._date = QDateEdit(QDate.currentDate())
        self._date.setDisplayFormat("yyyy-MM-dd")
        self._date.setMinimumHeight(34)
        self._date.setButtonSymbols(QDateEdit.ButtonSymbols.NoButtons)
        r3.addLayout(self._field(t("mark_purchased.purchase_date"), self._date), 1)
        self._edition = TextField(t("mark_purchased.edition_placeholder"))
        r3.addLayout(self._field(t("mark_purchased.edition"), self._edition), 1)
        grid.addLayout(r3)
        lay.addLayout(grid)

        # savings / error line
        srow = hbox(spacing=SP["sm"])
        self._savings_icon = QLabel()
        self._savings_icon.setFixedSize(14, 14)
        srow.addWidget(self._savings_icon)
        self._savings = label("", "body", color=C["green"])
        srow.addWidget(self._savings, 1)
        self._error = label("", "body", color=C["red"])
        srow.addWidget(self._error, 1)
        self._error.hide()
        lay.addLayout(srow)

        lay.addWidget(Divider())

        # buttons
        brow = hbox(spacing=SP["sm"])
        brow.addWidget(Button(t("actions.cancel"), "ghost", on_click=self.reject))
        brow.addStretch()
        self._confirm = Button(t("mark_purchased.confirm"), "primary", icon="check", on_click=self._confirm_clicked)
        self._confirm.setDefault(True)
        brow.addWidget(self._confirm)
        lay.addLayout(brow)

    @staticmethod
    def _field(title: str, widget: QWidget):
        col = vbox(spacing=SP["xs"])
        col.setAlignment(Qt.AlignmentFlag.AlignTop)
        col.addWidget(label(title, "muted"))
        col.addWidget(widget)
        return col

    # ── tabs ─────────────────────────────────────────────────────────────────

    def _set_tab(self, key: str) -> None:
        self._tab = key
        if key == "individual":
            self._list_stack.hide()
            self.adjustSize()
            return
        self._list_stack.setCurrentWidget(self._list_pages[key])
        self._list_stack.show()
        if self._items[key] is None and key not in self._loading:
            self._fetch(key)
        self.adjustSize()

    def _fetch(self, key: str) -> None:
        self._loading.add(key)
        self._show_skeleton(key)
        app_id = str(self._game.app_id or "")
        country = get_settings().get("country", "us") or "us"

        def work():
            from services import bundle_api
            if not app_id:
                return []
            if key == "editions":
                return bundle_api.get_editions_for_app(app_id, country=country)
            return bundle_api.get_bundles_enriched(app_id, country=country)

        def on_done(result):
            self._loading.discard(key)
            if isinstance(result, Exception):
                log.warning("%s fetch failed: %s", key, result)
                self._show_error(key, result)
                return
            items = list(result or [])
            if key == "editions" and not items and self._game.price:
                p = self._game.price          # fallback: what we already know
                items = [{"name": i18n.t("mark_purchased.standard_edition"), "current": p.current,
                          "base": p.base, "discount": p.discount_pct, "currency": p.currency}]
            self._items[key] = items
            self._show_items(key, items)

        run_async(self, work, on_done=on_done)

    def _list_reset(self, key: str):
        lay = self._list_lays[key]
        clear_layout(lay)
        self._rows[key] = []
        return lay

    def _show_skeleton(self, key: str) -> None:
        lay = self._list_reset(key)
        for _ in range(3):
            row = hbox(margins=(SP["md"], SP["sm"], SP["md"], SP["sm"]), spacing=SP["md"])
            row.addWidget(Skeleton(16, 16, radius=8))
            col = vbox(spacing=SP["xs"])
            col.addWidget(Skeleton(180, 12))
            col.addWidget(Skeleton(110, 10))
            row.addLayout(col, 1)
            row.addWidget(Skeleton(64, 12))
            lay.addLayout(row)
        lay.addStretch()

    def _show_error(self, key: str, err: Exception) -> None:
        lay = self._list_reset(key)
        retry = Button(i18n.t("mark_purchased.retry"), "default", icon="refresh",
                       on_click=lambda: self._fetch(key))
        log.info("%s unavailable: %s", key, err)
        lay.addWidget(EmptyState("cloud-off", i18n.t("mark_purchased.load_error_title"),
                                 i18n.t("mark_purchased.load_error_sub"), action=retry))

    def _show_items(self, key: str, items: list[dict]) -> None:
        lay = self._list_reset(key)
        t = i18n.t
        if not items:
            lay.addWidget(EmptyState("package" if key == "bundles" else "layers",
                                     t(f"mark_purchased.no_{key}_title"), t(f"mark_purchased.no_{key}_sub")))
            return
        for item in items:
            if key == "editions":
                cur = item.get("currency") or "USD"
                sub = ""
                trailing = self._price_widget(item.get("current"), item.get("base"), item.get("discount"), cur)
            else:
                cur = item.get("currency") or "USD"
                parts = [t("mark_purchased.n_games", n=item.get("app_count", 0) or 0)]
                if item.get("wishlist_matches"):
                    parts.append(t("mark_purchased.n_in_wishlist", n=len(item["wishlist_matches"])))
                if item.get("already_purchased"):
                    parts.append(t("mark_purchased.n_already_owned", n=len(item["already_purchased"])))
                sub = " · ".join(parts)
                if item.get("price_unavailable") or item.get("price") is None:
                    trailing = label(t("mark_purchased.price_unavailable"), "muted")
                elif (item.get("price") or 0) > 0:
                    trailing = self._price_widget(item["price"], item.get("base_price"), item.get("discount"), cur)
                else:
                    trailing = label(t("mark_purchased.free_included"), "muted")
            check = QLabel()
            check.setFixedSize(16, 16)
            row = ListRow(item.get("name", "—"), sub, leading=check, trailing=trailing)
            row.clicked.connect(lambda it=item, k=key, r=row: self._select(k, r, it))
            self._rows[key].append((row, check))
            lay.addWidget(row)
        lay.addStretch()
        first = self._rows[key][0]
        self._select(key, first[0], items[0])

    @staticmethod
    def _price_widget(current, base, disc, cur: str) -> QWidget:
        box = QWidget()
        h = hbox(box, (0, 0, 0, 0), SP["xs"])
        if disc:
            h.addWidget(Pill(discount(disc), "green"))
        h.addWidget(label(money(current, cur), "mono", weight=QFont.Weight.Bold))
        return box

    def _select(self, key: str, row: ListRow, item: dict) -> None:
        for r, chk in self._rows[key]:
            if r is row:
                chk.setPixmap(icons.pixmap("circle-check", C["accent"], 16))
            else:
                chk.clear()
        self._selected = item
        if key == "editions":
            self._fill(item.get("current"), item.get("base"), item.get("currency"), item.get("name"))
        else:
            self._fill_bundle(item)

    # ── form ─────────────────────────────────────────────────────────────────

    def _fill_from_game(self) -> None:
        p = self._game.price
        if p:
            self._fill(p.current, p.base, p.currency, None)
        else:
            self._recalc()

    def _fill(self, current, base, currency, edition: Optional[str]) -> None:
        if current is not None:
            self._price.setText(f"{float(current):.2f}")
        if base is not None:
            self._base.setText(f"{float(base):.2f}")
        elif current is not None:
            self._base.setText(f"{float(current):.2f}")
        if currency:
            self._currency.setText(str(currency).upper())
        if edition is not None:
            self._edition.setText(edition)
        self._recalc()

    def _fill_bundle(self, b: dict) -> None:
        """Bundle → form. Base comes from Steam's strikethrough price when present,
        otherwise it is derived from the discount so base never equals final."""
        self._edition.setText(b.get("name") or i18n.t("mark_purchased.bundle_label"))
        if b.get("price_unavailable") or b.get("price") is None:
            self._recalc()
            return
        final = float(b.get("price") or 0)
        if final <= 0:
            self._recalc()
            return
        disc = int(b.get("discount") or 0)
        raw_base = b.get("base_price")
        if raw_base is not None:
            base = round(float(raw_base), 2)
        elif 0 < disc < 100:
            base = round(final / (1 - disc / 100), 2)
        else:
            base = final
        self._fill(final, base, b.get("currency"), None)

    def _recalc(self) -> None:
        price, base = _num(self._price.text()), _num(self._base.text())
        cur = (self._currency.text() or "USD").upper()
        self._error.hide()
        self._savings.show()
        if price is None or base is None or base <= 0 or price > base:
            self._disc_pill.setText("—"); self._disc_pill.set_tone("neutral")
            self._savings.setText(i18n.t("mark_purchased.no_savings") if price is not None else "")
            self._savings_icon.clear()
            return
        d = round((1 - price / base) * 100)
        saved = base - price
        if d > 0:
            self._disc_pill.setText(discount(d)); self._disc_pill.set_tone("green")
            self._savings.setText(i18n.t("mark_purchased.savings", amount=money(saved, cur), pct=pct(d)))
            self._savings_icon.setPixmap(icons.pixmap("piggy-bank", C["green"], 14))
        else:
            self._disc_pill.setText("—"); self._disc_pill.set_tone("neutral")
            self._savings.setText(i18n.t("mark_purchased.no_savings"))
            self._savings_icon.clear()

    def _fail(self, field: TextField, msg: str) -> None:
        field.set_error(True)
        animations.shake(field)
        self._savings.hide()
        self._error.setText(msg)
        self._error.show()
        field.setFocus()

    # ── confirm ──────────────────────────────────────────────────────────────

    def _confirm_clicked(self) -> None:
        if self._saving:
            return
        for f in (self._price, self._base):
            f.set_error(False)
        price = _num(self._price.text())
        if price is None or price < 0:
            self._fail(self._price, i18n.t("mark_purchased.invalid_price"))
            return
        base = _num(self._base.text())
        if base is None:
            base = price
        if base < 0:
            self._fail(self._base, i18n.t("mark_purchased.invalid_base"))
            return
        currency = (self._currency.text().strip() or (self._game.price.currency if self._game.price else "USD")).upper()
        saved = max(0.0, base - price)
        disc = round(saved / base * 100) if base > 0 else 0
        edition = self._edition.text().strip() or i18n.t("mark_purchased.standard_edition")
        game = self._game
        purchase = Purchase(
            app_id=game.app_id, name=game.name,
            purchased_at=self._date.date().toString("yyyy-MM-dd"),
            price_paid=round(price, 2), base_price=round(base, 2), currency=currency,
            discount_pct=int(disc), edition=edition, saved=round(saved, 2),
        )

        self._saving = True
        self._confirm.set_loading(True, i18n.t("mark_purchased.saving"))

        def work():
            purchases.add(purchase)
            # canonical status constant — never a translated string (see data/status.py)
            game.status = STATUS_PURCHASED
            repo.update(game)
            if saved > 0:
                try:
                    from services.savings_reporter import report_saving
                    report_saving(saved, currency)
                except Exception as e:  # noqa: BLE001 — stats only, never blocks a purchase
                    log.info("savings report skipped: %s", e)
            return purchase

        def on_done(result):
            self._saving = False
            self._confirm.set_loading(False)
            if isinstance(result, Exception):
                self._savings.hide()
                self._error.setText(i18n.t("mark_purchased.save_failed", msg=str(result)))
                self._error.show()
                return
            if self._on_success:
                try:
                    self._on_success(result)
                except TypeError:
                    self._on_success()
            self.accept()

        run_async(self, work, on_done=on_done)
