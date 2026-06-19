import threading
from datetime import datetime
from typing import Callable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QScrollArea, QWidget, QFrame,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont

from config import COLORS
from data.models import Game, Purchase
from data.status import STATUS_PURCHASED
import data.purchase_repository as purchases
import data.repository as repo
import i18n
from ui.animations import shake_widget, pulse_button


BG     = COLORS["bg"]
PANEL  = COLORS["panel"]
CARD   = COLORS["card"]
CARD_H = COLORS["card_hover"]
BORDER = COLORS["border"]
TEXT   = COLORS["text"]
DIM    = COLORS["text_dim"]
BLUE   = COLORS["blue"]
GREEN  = COLORS["green"]
GOLD   = COLORS["gold"]


# ── Widget helpers ─────────────────────────────────────────────────────────────

def _lbl(text, size=11, bold=False, color=None, wrap=False) -> QLabel:
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold:
        f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or TEXT}; background-color:transparent;")
    l.setAutoFillBackground(False)
    if wrap:
        l.setWordWrap(True)
    return l


def _entry(text="", width=120) -> QLineEdit:
    e = QLineEdit(text)
    e.setFixedWidth(width)
    e.setFixedHeight(36)
    e.setStyleSheet(f"""
        QLineEdit {{
            background:{CARD}; color:{TEXT};
            border:1px solid {BORDER}; border-radius:4px;
            padding:0 10px; font-family:'Space Mono'; font-size:12px;
        }}
        QLineEdit:focus {{ border:1px solid {BLUE}; }}
    """)
    return e


# ── Signal bridge ─────────────────────────────────────────────────────────────

class _Sig(QObject):
    editions_ready = Signal(list)
    bundles_ready  = Signal(list)


# ── Dialog ────────────────────────────────────────────────────────────────────

class MarkPurchasedDialog(QDialog):

    def __init__(self, parent, game: Game, on_success: Callable, **kwargs):
        super().__init__(parent)
        self._game             = game
        self._on_success       = on_success
        self._editions: list   = []
        self._bundles: list | None = None   # None = still loading
        self._tab              = "individual"
        self._selected_edition: dict = {}
        self._selected_bundle:  dict = {}

        self._sig = _Sig()
        self._sig.editions_ready.connect(self._show_editions)
        self._sig.bundles_ready.connect(self._show_bundles)

        self.setWindowTitle(i18n.t("mark_purchased.title"))
        self.setFixedSize(560, 640)
        self.setStyleSheet(f"QDialog {{ background:{PANEL}; }}")
        self._build()

        threading.Thread(target=self._fetch_editions, daemon=True).start()
        threading.Thread(target=self._fetch_bundles,  daemon=True).start()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(0)

        # Title
        lay.addWidget(_lbl(self._game.name, 13, bold=True))
        lay.addSpacing(4)
        lay.addWidget(_lbl(i18n.t("mark_purchased.how_bought"), 10, color=DIM))
        lay.addSpacing(14)

        # ── Tab buttons ───────────────────────────────────────────────────────
        tab_row = QHBoxLayout()
        tab_row.setSpacing(10)
        self._btn_individual = self._tab_btn(i18n.t("mark_purchased.individually"), "individual")
        self._btn_bundle     = self._tab_btn(i18n.t("mark_purchased.in_bundle"),  "bundle")
        tab_row.addWidget(self._btn_individual)
        tab_row.addWidget(self._btn_bundle)
        tab_row.addStretch()
        lay.addLayout(tab_row)
        lay.addSpacing(14)

        # ── List area ─────────────────────────────────────────────────────────
        self._list_lbl = _lbl(i18n.t("mark_purchased.game_versions"), 9, bold=True, color=DIM)
        lay.addWidget(self._list_lbl)
        lay.addSpacing(6)

        self._list_scroll = QScrollArea()
        self._list_scroll.setFixedHeight(200)
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setObjectName("EditionScroll")
        self._list_scroll.setStyleSheet(f"""
            QScrollArea#EditionScroll {{
                border:1px solid {BORDER}; border-radius:8px; background:{BG};
            }}
            QScrollBar:vertical {{ background:{BG}; width:5px; border:none; }}
            QScrollBar::handle:vertical {{
                background:{BORDER}; border-radius:2px; min-height:20px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        self._list_container = QWidget()
        self._list_container.setObjectName("EditionContainer")
        self._list_container.setStyleSheet(
            f"QWidget#EditionContainer {{ background:{BG}; }}"
        )
        self._list_lay = QVBoxLayout(self._list_container)
        self._list_lay.setContentsMargins(6, 6, 6, 6)
        self._list_lay.setSpacing(6)
        self._list_lay.addWidget(_lbl(i18n.t("mark_purchased.loading"), 10, color=BLUE))
        self._list_scroll.setWidget(self._list_container)
        lay.addWidget(self._list_scroll)
        lay.addSpacing(18)

        # ── Price fields ──────────────────────────────────────────────────────
        price_grid = QHBoxLayout()
        price_grid.setSpacing(16)

        def _price_col(label, attr, default="0.00"):
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addWidget(_lbl(label, 9, bold=True, color=DIM))
            e = _entry(default)
            setattr(self, attr, e)
            col.addWidget(e)
            return col

        current  = self._game.price.current      if self._game.price else 0.0
        base     = self._game.price.base         if self._game.price else 0.0
        disc     = self._game.price.discount_pct if self._game.price else 0
        currency = self._game.price.currency     if self._game.price else "USD"

        price_grid.addLayout(_price_col(i18n.t("mark_purchased.base_price_col"),  "_base_edit",  f"{base:.2f}"))
        price_grid.addLayout(_price_col(i18n.t("mark_purchased.discount_col"),    "_disc_edit",  f"{disc}%"))
        price_grid.addLayout(_price_col(i18n.t("mark_purchased.final_price_col"), "_price_edit", f"{current:.2f}"))

        cur_col = QVBoxLayout()
        cur_col.setSpacing(4)
        cur_col.addWidget(_lbl("", 9))
        self._currency_lbl = _lbl(currency, 12, bold=True, color=DIM)
        self._currency_lbl.setFixedHeight(36)
        self._currency_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        cur_col.addWidget(self._currency_lbl)
        price_grid.addLayout(cur_col)
        price_grid.addStretch()
        lay.addLayout(price_grid)

        self._price_edit.textChanged.connect(self._on_price_changed)
        self._base_edit.textChanged.connect(self._on_price_changed)

        # ── Date ──────────────────────────────────────────────────────────────
        lay.addSpacing(8)
        date_row = QHBoxLayout()
        date_row.addWidget(_lbl(i18n.t("mark_purchased.purchase_date_col"), 9, bold=True, color=DIM))
        date_row.addSpacing(12)
        self._date_edit = _entry(datetime.now().strftime("%Y-%m-%d"), 130)
        date_row.addWidget(self._date_edit)
        date_row.addWidget(_lbl(i18n.t("mark_purchased.date_hint"), 9, color=DIM))
        date_row.addStretch()
        lay.addLayout(date_row)

        # Savings preview
        lay.addSpacing(8)
        self._savings_lbl = _lbl("", 11, bold=True, color=GREEN)
        lay.addWidget(self._savings_lbl)
        self._update_savings()
        lay.addStretch()

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setObjectName("Divider")
        div.setStyleSheet(f"QFrame#Divider {{ color:{BORDER}; }}")
        lay.addWidget(div)
        lay.addSpacing(10)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        cancel = QPushButton(i18n.t("mark_purchased.cancel"))
        cancel.setObjectName("CancelBtn")
        cancel.setFixedSize(90, 38)
        cancel.setStyleSheet(f"""
            QPushButton#CancelBtn {{
                background:transparent; color:{DIM};
                border:1px solid {BORDER}; border-radius:6px;
                font-family:'Space Mono'; font-size:11px;
            }}
            QPushButton#CancelBtn:hover {{ background:{CARD_H}; color:{TEXT}; }}
        """)
        cancel.clicked.connect(self.reject)

        confirm = QPushButton(i18n.t("mark_purchased.confirm_btn"))
        confirm.setObjectName("ConfirmBtn")
        confirm.setFixedHeight(38)
        confirm.setStyleSheet(f"""
            QPushButton#ConfirmBtn {{
                background:{GREEN}; color:#000;
                border:none; border-radius:6px;
                font-family:'Space Mono'; font-size:12px; font-weight:bold;
                padding:0 24px;
            }}
            QPushButton#ConfirmBtn:hover {{ background:#86efac; }}
        """)
        confirm.clicked.connect(self._confirm)

        btn_row.addWidget(cancel)
        btn_row.addStretch()
        btn_row.addWidget(confirm)
        lay.addLayout(btn_row)

        self._set_tab("individual")

    # ── Tab ───────────────────────────────────────────────────────────────────

    def _tab_btn(self, label: str, key: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setFixedHeight(40)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(self._tab_style(False))
        btn.clicked.connect(lambda: self._set_tab(key))
        return btn

    def _tab_style(self, active: bool) -> str:
        if active:
            return f"""
                QPushButton {{
                    background:{GREEN}; color:#000;
                    border:none; border-radius:8px;
                    font-family:'Space Mono'; font-size:11px; font-weight:bold;
                    padding:0 18px;
                }}
            """
        return f"""
            QPushButton {{
                background:{CARD}; color:{DIM};
                border:1px solid {BORDER}; border-radius:8px;
                font-family:'Space Mono'; font-size:11px;
                padding:0 18px;
            }}
            QPushButton:hover {{ background:{CARD_H}; color:{TEXT}; }}
        """

    def _set_tab(self, key: str):
        self._tab = key
        self._btn_individual.setStyleSheet(self._tab_style(key == "individual"))
        self._btn_bundle.setStyleSheet(self._tab_style(key == "bundle"))
        self._btn_individual.setChecked(key == "individual")
        self._btn_bundle.setChecked(key == "bundle")

        if key == "individual":
            self._list_lbl.setText(i18n.t("mark_purchased.game_versions"))
            if self._editions:
                self._show_editions(self._editions)
            else:
                self._clear_list()
                self._list_lay.addWidget(_lbl(i18n.t("mark_purchased.loading_editions"), 10, color=BLUE))
        else:
            self._list_lbl.setText(i18n.t("mark_purchased.game_bundles"))
            if self._bundles is None:
                self._clear_list()
                self._list_lay.addWidget(_lbl(i18n.t("mark_purchased.loading_bundles"), 10, color=BLUE))
            else:
                self._show_bundles(self._bundles)

    # ── List helpers ──────────────────────────────────────────────────────────

    def _clear_list(self):
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)

    def _make_row_card(self, title: str, subtitle: str = "",
                       price_str: str = "", selected: bool = False) -> QFrame:
        """
        A selectable card row.
        Uses QFrame#RowCard to prevent style bleeding into child labels.
        """
        card = QFrame()
        card.setObjectName("RowCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_card_style(card, selected)

        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(8)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(_lbl(title, 11, bold=True))
        if subtitle:
            text_col.addWidget(_lbl(subtitle, 9, color=DIM))
        row.addLayout(text_col, 1)

        if price_str:
            row.addWidget(_lbl(price_str, 11, bold=True,
                               color=GOLD if selected else TEXT))
        return card

    @staticmethod
    def _apply_card_style(card: QFrame, active: bool):
        card.setStyleSheet(f"""
            QFrame#RowCard {{
                background:{'#1c2a3a' if active else CARD};
                border:{'2' if active else '1'}px solid {BLUE if active else BORDER};
                border-radius:8px;
            }}
        """)

    def _select_card(self, cards: list[QFrame], chosen: QFrame):
        for c in cards:
            self._apply_card_style(c, c is chosen)
            # Update price label colour inside the card
            row = c.layout()
            for i in range(row.count()):
                w = row.itemAt(i).widget()
                if isinstance(w, QLabel):
                    w.setStyleSheet(
                        f"color:{GOLD if c is chosen else TEXT};"
                        f" background-color:transparent;"
                    )

    # ── Editions ──────────────────────────────────────────────────────────────

    def _fetch_editions(self):
        try:
            from services.bundle_api import get_editions_for_app
            from ui.settings_loader import get_settings
            country = get_settings().get("country", "mx")

            editions = get_editions_for_app(self._game.app_id, country=country)

            # Final fallback: use local game price if API returned nothing
            if not editions:
                editions = [{
                    "name":     i18n.t("mark_purchased.standard_edition"),
                    "current":  self._game.price.current      if self._game.price else 0.0,
                    "base":     self._game.price.base         if self._game.price else 0.0,
                    "discount": self._game.price.discount_pct if self._game.price else 0,
                    "currency": self._game.price.currency     if self._game.price else "USD",
                }]

            self._editions = editions
            self._sig.editions_ready.emit(self._editions)

        except Exception as e:
            print(f"[MarkPurchased] editions fetch error: {e}")
            self._sig.editions_ready.emit([])

    def _show_editions(self, editions: list):
        if self._tab != "individual":
            return
        self._clear_list()

        if not editions:
            self._list_lay.addWidget(
                _lbl(i18n.t("mark_purchased.no_editions"), 10, color=DIM))
            return

        cards: list[QFrame] = []

        for i, ed in enumerate(editions):
            first     = (i == 0)
            price_str = ""
            if ed.get("current"):
                if ed.get("discount", 0) > 0:
                    price_str = f"-{ed['discount']}%  ${ed['current']:.0f}"
                else:
                    price_str = f"${ed['current']:.0f}"

            card = self._make_row_card(ed["name"], "", price_str, selected=first)
            card.mousePressEvent = (
                lambda _event, c=card, e=ed, cl=cards: self._on_edition_click(c, e, cl)
            )
            cards.append(card)
            self._list_lay.addWidget(card)

            if first:
                self._apply_edition(ed)

        self._list_lay.addStretch()

    def _on_edition_click(self, card: QFrame, ed: dict, cards: list[QFrame]):
        self._selected_edition = ed
        self._select_card(cards, card)
        self._apply_edition(ed)

    def _apply_edition(self, ed: dict):
        """Push edition data into price fields."""
        self._selected_edition = ed
        self._base_edit.setText(f"{ed.get('base', 0):.2f}")
        self._price_edit.setText(f"{ed.get('current', 0):.2f}")
        self._disc_edit.setText(f"{ed.get('discount', 0)}%")
        self._currency_lbl.setText(ed.get("currency", "USD"))
        self._update_savings()

    # ── Bundles ───────────────────────────────────────────────────────────────

    def _fetch_bundles(self):
        try:
            from services.bundle_api import get_bundles_enriched
            from ui.settings_loader import get_settings
            country = get_settings().get("country", "mx")
            bundles = get_bundles_enriched(self._game.app_id, country=country)
            self._bundles = bundles
            self._sig.bundles_ready.emit(bundles)
        except Exception as e:
            print(f"[MarkPurchased] bundles fetch error: {e}")
            self._bundles = []
            self._sig.bundles_ready.emit([])

    def _show_bundles(self, bundles: list):
        if self._tab != "bundle":
            return
        self._clear_list()

        if not bundles:
            self._list_lay.addWidget(
                _lbl(i18n.t("mark_purchased.no_bundles"), 10, color=DIM))
            return

        cards: list[QFrame] = []

        for i, b in enumerate(bundles):
            first   = (i == 0)
            n_games = b.get("app_count", 0)

            # Price string — show "Price unavailable" when no price data
            price_unavailable = b.get("price_unavailable", False) or b.get("price") is None
            if price_unavailable:
                price_str = i18n.t("mark_purchased.price_unavailable")
            elif b.get("price", 0) > 0:
                price_str = f"${b['price']:.0f} {b.get('currency', '')}"
            else:
                price_str = i18n.t("mark_purchased.free_included")

            # Subtitle: game count + wishlist hint
            subtitle_parts = [i18n.t("mark_purchased.n_games").format(n=n_games)]
            if b.get("wishlist_matches"):
                subtitle_parts.append(i18n.t("mark_purchased.n_in_wishlist").format(n=len(b["wishlist_matches"])))
            if b.get("already_purchased"):
                subtitle_parts.append(i18n.t("mark_purchased.n_already_owned").format(n=len(b["already_purchased"])))
            subtitle = "  ·  ".join(subtitle_parts)

            card = self._make_row_card(b["name"], subtitle, price_str, selected=first)
            card.mousePressEvent = (
                lambda _event, c=card, bnd=b, cl=cards: self._on_bundle_click(c, bnd, cl)
            )
            cards.append(card)
            self._list_lay.addWidget(card)

            if first:
                self._apply_bundle(b)

        self._list_lay.addStretch()

    def _on_bundle_click(self, card: QFrame, bundle: dict, cards: list[QFrame]):
        self._selected_bundle = bundle
        self._select_card(cards, card)
        self._apply_bundle(bundle)

    def _apply_bundle(self, bundle: dict):
        """
        Push bundle data into the BASE PRICE / DISCOUNT / FINAL PRICE fields.

        Rules:
          • If price is unavailable (ajaxresolvebundles has no price data and the
            HTML scrape also found nothing), leave all fields as-is so the user can
            enter the price manually.
          • If a real price exists:
            - FINAL PRICE  = bundle["price"]
            - BASE PRICE   = bundle["base_price"] if Steam provided the original price
                             in the HTML strikethrough element, otherwise calculated as:
                               base = final / (1 - discount/100)
                             Falls back to final when discount is 0, <0, or ≥100.
            - DISCOUNT     = bundle["discount"]  (integer %)

        This ensures BASE PRICE is never shown as equal to FINAL PRICE when a
        discount is present (the previous bug: both fields were set to `price`).
        """
        self._selected_bundle = bundle

        price_unavailable = (
            bundle.get("price_unavailable", False)
            or bundle.get("price") is None
        )
        if price_unavailable:
            # Leave fields editable — user enters the price they paid manually
            self._update_savings()
            return

        final_price = float(bundle.get("price", 0) or 0)
        if final_price <= 0:
            self._update_savings()
            return

        discount = int(bundle.get("discount", 0) or 0)

        # Prefer the exact original price from Steam HTML (discount_original_price).
        # Fall back to deriving it mathematically when Steam didn't provide it.
        raw_base = bundle.get("base_price")
        if raw_base is not None:
            base_price = round(float(raw_base), 2)
        elif 0 < discount < 100:
            base_price = round(final_price / (1 - discount / 100), 2)
        else:
            base_price = final_price

        self._base_edit.setText(f"{base_price:.2f}")
        self._price_edit.setText(f"{final_price:.2f}")
        self._disc_edit.setText(f"{discount}%")
        self._currency_lbl.setText(bundle.get("currency", "USD"))
        self._update_savings()

    # ── Price logic ───────────────────────────────────────────────────────────

    def _on_price_changed(self):
        try:
            base  = float(self._base_edit.text().replace(",", ""))
            final = float(self._price_edit.text().replace(",", ""))
            if base > 0 and final <= base:
                disc = round((1 - final / base) * 100)
                self._disc_edit.blockSignals(True)
                self._disc_edit.setText(f"{disc}%")
                self._disc_edit.blockSignals(False)
        except ValueError:
            pass
        self._update_savings()

    def _update_savings(self):
        try:
            base  = float(self._base_edit.text().replace(",", ""))
            final = float(self._price_edit.text().replace(",", ""))
            saved = base - final
            if saved > 0:
                cur = self._currency_lbl.text()
                self._savings_lbl.setText(i18n.t("mark_purchased.you_saved").format(amount=f"{saved:,.2f}", currency=cur))
            else:
                self._savings_lbl.setText("")
        except ValueError:
            self._savings_lbl.setText("")

    # ── Confirm ───────────────────────────────────────────────────────────────

    def _confirm(self):
        try:
            price_paid = float(self._price_edit.text().replace(",", ""))
            base_price = float(self._base_edit.text().replace(",", ""))
        except ValueError:
            return

        currency   = self._currency_lbl.text() or "USD"
        saved      = max(0.0, base_price - price_paid)
        disc_str   = self._disc_edit.text().replace("%", "").strip()
        try:
            disc = int(disc_str)
        except ValueError:
            disc = int(saved / base_price * 100) if base_price > 0 else 0

        edition_name = (
            self._selected_edition.get("name", i18n.t("mark_purchased.standard_edition"))
            if self._tab == "individual"
            else self._selected_bundle.get("name", i18n.t("mark_purchased.bundle_label"))
        )

        p = Purchase(
            app_id       = self._game.app_id,
            name         = self._game.name,
            edition      = edition_name,
            price_paid   = price_paid,
            base_price   = base_price,
            currency     = currency,
            saved        = saved,
            discount_pct = disc,
            purchased_at = (
                self._date_edit.text().strip()
                or datetime.now().strftime("%Y-%m-%d")
            ),
        )
        purchases.add(p)

        # Report saving to backend (optional service)
        if saved > 0:
            try:
                from services.savings_reporter import report_saving
                report_saving(amount=saved, currency=currency)
            except Exception:
                pass

        # Mark game as purchased. IMPORTANT: this must be the canonical,
        # language-independent status constant — never a translated i18n
        # string — or the game becomes invisible to every status filter
        # the moment the locale changes (see data/status.py for details).
        self._game.status = STATUS_PURCHASED
        repo.update(self._game)

        # Brief pulse before closing
        try:
            pulse_button(self._confirm_btn, color=COLORS["green"])
            QTimer.singleShot(160, self.accept)
        except Exception:
            self.accept()
        if self._on_success:
            try:
                self._on_success(p)
            except TypeError:
                self._on_success()