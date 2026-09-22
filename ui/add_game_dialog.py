"""
Add a Steam game to the wishlist.

    AddGameDialog(parent_window, on_success=...)   .exec()

Search-as-you-type (300 ms debounce) against services.steam_api.search_games,
or paste an AppID / store URL. Picking a result fetches the store details,
current price and (when IsThereAnyDeal is configured) the all-time low, all
through run_async. Confirming builds a data.models.Game, saves it and starts
the cover download on the parent window so it outlives the dialog.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QStackedWidget, QWidget

import i18n
import data.repository as repo
import services.price_history as price_history
import services.steam_api as steam
import services.steamgriddb as sgdb
from data.models import Game
from ui.animations import clear_layout, shake
from ui.async_bridge import run_async
from ui.components import (Button, Card, ElidedLabel, EmptyState, ListRow, Pill, SearchField,
                           Segmented, Skeleton, TextField, hbox, label, scroll_area, vbox)
from ui.format import discount, money
from ui.library_view import translate_genres
from ui.settings_loader import get_settings
from ui.settings_view import CURRENCY_OF
from ui.theme import C, SP

DIALOG_WIDTH = 560
RESULTS_HEIGHT = 236
PREVIEW_MIN_HEIGHT = 112
MAX_RESULTS = 10
SEARCH_DEBOUNCE_MS = 300
MIN_QUERY = 2
PRIORITIES = ("S", "A", "B", "C")
_APP_URL = re.compile(r"store\.steampowered\.com/app/(\d+)", re.IGNORECASE)
_PROBE_URL = "https://store.steampowered.com/"


def extract_app_id(text: str) -> Optional[str]:
    """'1245620', '#1245620' or any store URL containing /app/<id> -> '1245620'."""
    text = (text or "").strip()
    m = _APP_URL.search(text)
    if m:
        return m.group(1)
    digits = text.lstrip("#")
    return digits if digits.isdigit() and len(digits) >= 3 else None


class _NotFound(Exception):
    """Steam has no store page for that AppID."""


class _Unreachable(Exception):
    """The Steam store could not be reached."""


class AddGameDialog(QDialog):
    """Search Steam, preview, pick a priority, add to the wishlist."""

    def __init__(self, parent, on_success: Optional[Callable] = None, **_):
        super().__init__(parent)
        self._on_success = on_success or (lambda: None)
        self._fetched: Optional[tuple[dict, object, object]] = None    # (meta, price, history)
        self._seq = 0                    # ignores stale async results
        self._rows: list[tuple[str, Pill]] = []
        self._last_query = ""
        self.setWindowTitle(i18n.t("add_game.title"))
        self.setFixedWidth(DIALOG_WIDTH)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._run_search)
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        t = i18n.t
        lay = vbox(self, (SP["xl"], SP["xl"], SP["xl"], SP["xl"]), SP["md"])

        head = vbox(spacing=2)
        head.addWidget(label(t("add_game.title"), "title"))
        head.addWidget(label(t("add_game.subtitle"), "muted"))
        lay.addLayout(head)

        row = hbox(spacing=SP["sm"])
        self._search = SearchField(t("add_game.search_placeholder"))
        self._search.textChanged.connect(self._on_search_text)
        self._search.returnPressed.connect(self._run_search)
        row.addWidget(self._search, 1)
        self._appid = TextField(t("add_game.appid_placeholder"), icon="hash")
        self._appid.setFixedWidth(180)
        self._appid.returnPressed.connect(self._lookup_manual)
        self._appid.editingFinished.connect(self._lookup_manual)
        self._appid.textChanged.connect(lambda _t: self._appid.set_error(False))
        row.addWidget(self._appid)
        lay.addLayout(row)

        # results (idle · loading · list · empty · error)
        self._stack = QStackedWidget()
        self._stack.setFixedHeight(RESULTS_HEIGHT)
        self._idle = EmptyState("search", t("add_game.idle_title"), t("add_game.idle_subtitle"))
        self._skeleton = QWidget()
        sk = vbox(self._skeleton, spacing=SP["sm"])
        for _ in range(4):
            c = Card(padding=SP["md"], spacing=0)
            r = hbox(spacing=SP["md"])
            r.addWidget(Skeleton(56, 16))
            r.addWidget(Skeleton(200, 12))
            r.addStretch()
            r.addWidget(Skeleton(48, 12))
            c.body.addLayout(r)
            sk.addWidget(c)
        sk.addStretch()
        self._list_box = QWidget()
        self._list_lay = vbox(self._list_box, (0, 0, SP["sm"], 0), SP["sm"])
        self._list_lay.addStretch()
        self._list_scroll = scroll_area(self._list_box)
        self._empty = EmptyState("search", t("add_game.no_results_title"), "")
        self._retry_btn = Button(t("add_game.retry"), icon="refresh", on_click=self._run_search)
        self._error = EmptyState("cloud-off", t("add_game.network_title"), t("add_game.network_subtitle"),
                                 action=self._retry_btn)
        for w in (self._idle, self._skeleton, self._list_scroll, self._empty, self._error):
            self._stack.addWidget(w)
        lay.addWidget(self._stack)

        # preview
        self._preview = Card(padding=SP["lg"], spacing=SP["sm"])
        self._preview.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self._preview_idle()
        lay.addWidget(self._preview)

        # priority + notes
        row = hbox(spacing=SP["md"])
        row.addWidget(label(t("game.priority"), "dim"))
        self._priority = Segmented([(p, p) for p in PRIORITIES], current="B")
        row.addWidget(self._priority)
        self._notes = TextField(t("add_game.notes_placeholder"), icon="newspaper")
        row.addWidget(self._notes, 1)
        lay.addLayout(row)

        self._form_error = label("", "muted", color=C["red"], wrap=True)
        self._form_error.hide()
        lay.addWidget(self._form_error)

        lay.addSpacing(SP["sm"])
        foot = hbox(spacing=SP["sm"])
        foot.addWidget(Button(t("actions.cancel"), variant="ghost", on_click=self.reject))
        foot.addStretch()
        self._add_btn = Button(t("add_game.confirm"), variant="primary", icon="plus", on_click=self._add)
        self._add_btn.setEnabled(False)
        foot.addWidget(self._add_btn)
        lay.addLayout(foot)

        self._search.setFocus()

    # ── search ───────────────────────────────────────────────────────────────

    @staticmethod
    def _cc() -> str:
        return (get_settings().get("country") or "us").lower()

    def _set_form_error(self, text: str) -> None:
        self._form_error.setText(text)
        self._form_error.setVisible(bool(text))

    def _on_search_text(self, _text: str) -> None:
        self._search.set_error(False)
        self._set_form_error("")
        self._debounce.start()

    def _run_search(self) -> None:
        self._debounce.stop()
        query = self._search.text().strip()
        app_id = extract_app_id(query)
        if app_id:
            self._select(app_id)
            return
        if len(query) < MIN_QUERY:
            self._stack.setCurrentWidget(self._idle)
            return
        self._last_query = query
        self._seq += 1
        seq = self._seq
        cc = self._cc()
        self._stack.setCurrentWidget(self._skeleton)

        def work():
            results = steam.search_games(query, MAX_RESULTS, cc)
            if not results:
                from services._http import SESSION
                try:                       # search_games swallows errors: probe once to tell them apart
                    SESSION.get(_PROBE_URL, timeout=5)
                except Exception as e:     # noqa: BLE001
                    raise _Unreachable(str(e)) from e
            return results

        def on_done(result):
            if seq != self._seq:
                return
            if isinstance(result, Exception):
                self._stack.setCurrentWidget(self._error)
                return
            self._show_results(result, cc)

        run_async(self, work, on_done=on_done)

    def _show_results(self, results: list[dict], cc: str) -> None:
        t = i18n.t
        clear_layout(self._list_lay)
        self._rows = []
        if not results:
            self._empty.subtitle.setText(t("add_game.no_results_subtitle", q=self._last_query))
            self._empty.subtitle.setVisible(True)
            self._stack.setCurrentWidget(self._empty)
            return
        currency = CURRENCY_OF.get(cc, "USD")
        for r in results:
            app_id = str(r.get("app_id") or r.get("id") or "")
            if not app_id:
                continue
            price = r.get("price")
            trailing = None
            if price is not None:
                trailing = label(money(price, currency) if price > 0 else t("add_game.free"), "mono",
                                 color=C["green"] if price > 0 else C["accent"])
            pill = Pill(app_id, "neutral")
            row = ListRow(r.get("name", ""), leading=pill, trailing=trailing)
            row.clicked.connect(lambda a=app_id: self._select(a))
            self._list_lay.addWidget(row)
            self._rows.append((app_id, pill))
        self._list_lay.addStretch()
        self._stack.setCurrentWidget(self._list_scroll)

    def _lookup_manual(self) -> None:
        text = self._appid.text().strip()
        if not text:
            return
        app_id = extract_app_id(text)
        if not app_id:
            self._appid.set_error(True)
            shake(self._appid)
            self._set_form_error(i18n.t("add_game.invalid_appid"))
            return
        self._select(app_id)

    # ── preview ──────────────────────────────────────────────────────────────

    def _select(self, app_id: str) -> None:
        t = i18n.t
        for aid, pill in self._rows:
            pill.set_tone("accent" if aid == app_id else "neutral")
        self._fetched = None
        self._add_btn.setEnabled(False)
        self._set_form_error("")
        if repo.exists(app_id):
            existing = repo.get_by_app_id(app_id)
            self._preview_message("triangle-alert", C["gold"],
                                  t("add_game.already_added", name=existing.name if existing else app_id))
            return
        self._seq += 1
        seq = self._seq
        cc = self._cc()
        self._preview_loading()

        def work():
            data = steam.get_app_details(app_id, country=cc)
            if not data:
                raise _NotFound(app_id)
            meta = steam.parse_metadata(data)
            meta["app_id"] = app_id
            meta["steam_url"] = f"https://store.steampowered.com/app/{app_id}"
            price = steam.parse_price(data)
            hist = price_history.get_price_history(app_id, country=cc)
            return meta, price, hist

        def on_done(result):
            if seq != self._seq:
                return
            if isinstance(result, _NotFound):
                self._preview_message("circle-x", C["red"], t("add_game.error_not_found"))
                return
            if isinstance(result, Exception):
                self._preview_message("cloud-off", C["red"], t("add_game.error_api"))
                return
            self._fetched = result
            self._render_preview(*result, cc)
            self._add_btn.setEnabled(True)

        run_async(self, work, on_done=on_done)

    def _preview_idle(self) -> None:
        body = self._preview.body
        clear_layout(body)
        body.addWidget(label(i18n.t("add_game.section_preview"), "eyebrow"))
        body.addWidget(label(i18n.t("add_game.preview_placeholder"), "muted"))
        body.addStretch()

    def _preview_loading(self) -> None:
        body = self._preview.body
        clear_layout(body)
        body.addWidget(Skeleton(220, 16))
        body.addWidget(Skeleton(160, 11))
        body.addWidget(Skeleton(90, 11))
        body.addWidget(label(i18n.t("add_game.preview_loading"), "muted"))

    def _preview_message(self, icon: str, color: str, text: str) -> None:
        from ui import icons
        body = self._preview.body
        clear_layout(body)
        row = hbox(spacing=SP["sm"])
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon, color, 16))
        row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(label(text, "body", wrap=True), 1)
        body.addLayout(row)
        body.addStretch()

    def _render_preview(self, meta: dict, price, hist, cc: str) -> None:
        t = i18n.t
        body = self._preview.body
        clear_layout(body)
        row = hbox(spacing=SP["lg"])
        col = vbox(spacing=2)
        col.addWidget(ElidedLabel(meta.get("name") or "—", "h2"))
        bits = [meta.get("developer") or "", str(meta.get("release_year") or t("add_game.unknown_year"))]
        col.addWidget(ElidedLabel(" · ".join(b for b in bits if b), "dim"))
        genre = translate_genres(meta.get("genre") or "")
        col.addWidget(ElidedLabel(genre or "—", "muted"))
        col.addStretch()
        row.addLayout(col, 1)

        right_w = QWidget()
        right = vbox(right_w, spacing=2)
        align = Qt.AlignmentFlag.AlignRight
        if price is None:
            right.addWidget(label("—", "h2", family="mono", color=C["text_dim"], align=align))
        elif price.current <= 0:
            right.addWidget(label(t("add_game.free"), "h2", family="mono", color=C["accent"], align=align))
        else:
            on_sale = bool(price.is_on_sale and price.discount_pct)
            right.addWidget(label(money(price.current, price.currency), "h2", family="mono",
                                  color=C["green"] if on_sale else C["text"], align=align))
            if on_sale:
                sale = hbox(spacing=SP["xs"])
                sale.addStretch()
                sale.addWidget(label(money(price.base, price.currency), "muted"))
                sale.addWidget(Pill(discount(price.discount_pct), "green"))
                right.addLayout(sale)
        if hist and getattr(hist, "all_time_low", 0):
            low = money(hist.all_time_low, price.currency if price else CURRENCY_OF.get(cc, "USD"))
            when = f" · {hist.all_time_low_date}" if hist.all_time_low_date else ""
            low_row = hbox(spacing=SP["xs"])
            low_row.addStretch()
            low_row.addWidget(Pill(t("game.price_low").upper(), "neutral"))
            low_row.addWidget(label(f"{low}{when}", "muted"))
            right.addLayout(low_row)
        right.addStretch()
        row.addWidget(right_w, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(row)

    # ── add ──────────────────────────────────────────────────────────────────

    def _add(self) -> None:
        t = i18n.t
        if not self._fetched:
            self._search.set_error(True)
            shake(self._search)
            self._set_form_error(t("add_game.select_first"))
            return
        meta, price, hist = self._fetched
        app_id = meta.get("app_id", "")
        if repo.exists(app_id):
            self._set_form_error(t("add_game.already_added", name=meta.get("name", app_id)))
            self._add_btn.setEnabled(False)
            return
        cc = self._cc()
        game = Game(
            id=0, name=meta.get("name", ""), app_id=app_id,
            steam_url=meta.get("steam_url", ""), genre=meta.get("genre", ""),
            release_year=meta.get("release_year", 0) or 0, developer=meta.get("developer", ""),
            publisher=meta.get("publisher", ""), categories=meta.get("categories", ""),
            short_description=meta.get("short_description", ""),
            priority=self._priority.current() or "B", status="Wishlist",
            price=price, price_history=hist, notes=self._notes.text().strip(),
        )
        self._set_form_error("")
        self._add_btn.set_loading(True, t("add_game.adding"))

        def work():
            if game.price is not None:
                price_history.observe(app_id, game.price)
            if game.price_history is None:
                game.price_history = price_history.get_price_history(
                    app_id, country=cc, currency=game.price.currency if game.price else None)
            repo.add(game)
            return game

        def on_done(result):
            if isinstance(result, Exception):
                self._add_btn.set_loading(False)
                self._set_form_error(t("add_game.add_failed", msg=str(result) or type(result).__name__))
                return
            self._start_cover_download(result)
            self._on_success()
            self.accept()

        run_async(self, work, on_done=on_done)

    def _start_cover_download(self, game: Game) -> None:
        """Cover download is owned by the parent window so it survives accept()."""
        owner = self.parent()
        if owner is None:
            return
        api_key = get_settings().get("steamgriddb_key", "") or ""

        def on_done(path):
            if isinstance(path, Exception) or not path:
                return
            fresh = repo.get_by_app_id(game.app_id)
            if fresh is None:
                return
            fresh.cover_path = path
            repo.update(fresh)
            fn = getattr(owner, "on_data_changed", None)
            if callable(fn):
                fn()

        run_async(owner, lambda: sgdb.download_cover(game.app_id, api_key, game.name), on_done=on_done)
