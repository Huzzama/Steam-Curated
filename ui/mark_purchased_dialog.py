"""
Mark as Purchased dialog — PySide6.
Fetches Steam editions in background, shows cards with prices.
"""
import threading
from datetime import datetime
from typing import Callable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QScrollArea, QWidget, QFrame,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont

from config import COLORS
from data.models import Game, Purchase
import data.purchase_repository as purchases
import data.repository as repo
import i18n


class _Sig(QObject):
    editions_ready = Signal(list)


class MarkPurchasedDialog(QDialog):

    def __init__(self, parent, game: Game, on_success: Callable, **kwargs):
        super().__init__(parent)
        self._game       = game
        self._on_success = on_success
        self._editions: list[dict] = []
        self._selected_edition: dict = {}

        self._sig = _Sig()
        self._sig.editions_ready.connect(self._show_editions)

        self.setWindowTitle("Mark as Purchased")
        self.setFixedSize(500, 580)
        self.setStyleSheet(f"QDialog {{ background:{COLORS['panel']}; }}")
        self._build()
        threading.Thread(target=self._fetch_editions, daemon=True).start()

    def _lbl(self, text, size=11, bold=False, color=None):
        l = QLabel(text)
        f = QFont("Space Mono", size)
        if bold: f.setBold(True)
        l.setFont(f)
        l.setStyleSheet(f"color:{color or COLORS['text']}; background-color:transparent;")
        return l

    def _entry(self, text="", width=140):
        e = QLineEdit(text)
        e.setFixedWidth(width)
        e.setFixedHeight(34)
        e.setStyleSheet(f"""
            QLineEdit {{
                background:{COLORS['card']}; color:{COLORS['text']};
                border:1px solid {COLORS['border']}; border-radius:4px;
                padding:0 8px; font-family:'Space Mono'; font-size:11px;
            }}
        """)
        return e

    def _build(self):
        P = 20
        lay = QVBoxLayout(self)
        lay.setContentsMargins(P, P, P, P)
        lay.setSpacing(8)

        # Header
        lay.addWidget(self._lbl(i18n.t("mark_purchased.title"), 15, bold=True))
        lay.addWidget(self._lbl(self._game.name, 12,
                                color=COLORS["text_dim"]))

        # Divider
        d = QFrame(); d.setFrameShape(QFrame.Shape.HLine)
        d.setStyleSheet(f"color:{COLORS['border']};")
        lay.addWidget(d)

        # Edition label
        lay.addWidget(self._lbl(i18n.t("mark_purchased.edition_label"), 11, bold=True))
        self._loading_lbl = self._lbl(
            i18n.t("mark_purchased.fetching_editions"), 10, color=COLORS["blue"])
        lay.addWidget(self._loading_lbl)

        # Edition scroll area
        self._ed_scroll = QScrollArea()
        self._ed_scroll.setFixedHeight(160)
        self._ed_scroll.setWidgetResizable(True)
        self._ed_scroll.setStyleSheet(f"""
            QScrollArea {{ border:1px solid {COLORS['border']};
                           border-radius:6px; background:{COLORS['bg']}; }}
        """)
        self._ed_container = QWidget()
        self._ed_container.setStyleSheet(f"background:{COLORS['bg']};")
        self._ed_lay = QVBoxLayout(self._ed_container)
        self._ed_lay.setContentsMargins(4, 4, 4, 4)
        self._ed_lay.setSpacing(4)
        self._ed_scroll.setWidget(self._ed_container)
        lay.addWidget(self._ed_scroll)

        # Price paid
        lay.addWidget(self._lbl(i18n.t("mark_purchased.price_paid"), 11, bold=True))
        pr = QHBoxLayout()
        current = self._game.price.current if self._game.price else 0.0
        self._price_edit = self._entry(f"{current:.2f}")
        self._price_edit.textChanged.connect(self._update_savings)
        currency = self._game.price.currency if self._game.price else "USD"
        pr.addWidget(self._price_edit)
        pr.addWidget(self._lbl(currency, 12, color=COLORS["text_dim"]))
        pr.addStretch()
        lay.addLayout(pr)

        # Base price
        lay.addWidget(self._lbl(i18n.t("mark_purchased.full_price"), 11, bold=True))
        base = self._game.price.base if self._game.price else current
        self._base_edit = self._entry(f"{base:.2f}")
        self._base_edit.textChanged.connect(self._update_savings)
        lay.addWidget(self._base_edit)

        # Date
        lay.addWidget(self._lbl(i18n.t("mark_purchased.purchase_date"), 11, bold=True))
        date_row = QHBoxLayout()
        self._date_edit = self._entry(datetime.now().strftime("%Y-%m-%d"), 160)
        date_row.addWidget(self._date_edit)
        date_row.addWidget(self._lbl(i18n.t("mark_purchased.date_format"), 9, color=COLORS["text_dim"]))
        date_row.addStretch()
        lay.addLayout(date_row)

        # Savings preview
        self._savings_lbl = self._lbl("", 11, bold=True, color=COLORS["green"])
        lay.addWidget(self._savings_lbl)
        self._update_savings()

        lay.addStretch()

        # Divider
        d2 = QFrame(); d2.setFrameShape(QFrame.Shape.HLine)
        d2.setStyleSheet(f"color:{COLORS['border']};")
        lay.addWidget(d2)

        # Buttons
        btn_row = QHBoxLayout()
        cancel = QPushButton(i18n.t("actions.cancel"))
        cancel.setFixedSize(86, 34)
        cancel.clicked.connect(self.reject)
        cancel.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{COLORS['text_dim']};
                border:1px solid {COLORS['border']}; border-radius:6px;
                font-family:'Space Mono'; font-size:11px;
            }}
            QPushButton:hover {{ background:{COLORS['card_hover']}; }}
        """)
        btn_row.addWidget(cancel)
        btn_row.addStretch()

        confirm = QPushButton(i18n.t("mark_purchased.confirm"))
        confirm.setFixedSize(170, 34)
        confirm.clicked.connect(self._confirm)
        confirm.setStyleSheet(f"""
            QPushButton {{
                background:{COLORS['green']}; color:#000;
                border:none; border-radius:6px;
                font-family:'Space Mono'; font-size:12px; font-weight:bold;
            }}
            QPushButton:hover {{ background:#86efac; }}
        """)
        btn_row.addWidget(confirm)
        lay.addLayout(btn_row)

    # ── Editions ──────────────────────────────────────────────────────────────

    def _fetch_editions(self):
        try:
            import services.steam_api as steam
            from ui.settings_loader import get_settings
            country = get_settings().get("country", "mx")
            data    = steam.get_app_details(self._game.app_id, country=country)
            editions = []

            if data:
                currency = (data.get("price_overview") or {}).get("currency", "USD")
                po = data.get("price_overview", {})
                if po:
                    editions.append({
                        "name":     "Standard Edition",
                        "current":  po.get("final", 0) / 100,
                        "base":     po.get("initial", 0) / 100,
                        "discount": po.get("discount_percent", 0),
                        "currency": po.get("currency", "USD"),
                    })
                for pkg in data.get("package_groups", []):
                    for sub in pkg.get("subs", []):
                        try:
                            cur = int(sub.get("price_in_cents_with_discount", 0)) / 100
                        except (ValueError, TypeError):
                            continue
                        desc  = sub.get("option_text", "")
                        if not desc or desc.lower() in ("standard", "base game"):
                            continue
                        try:
                            disc_str = sub.get("percent_savings_text","").strip().replace("-","").replace("%","")
                            disc = int(disc_str) if disc_str else 0
                        except ValueError:
                            disc = 0
                        base_p = cur / (1 - disc/100) if disc > 0 else cur
                        name   = desc.split(" - ")[0].replace(self._game.name,"").strip(" -–") or desc
                        editions.append({
                            "name":     name,
                            "current":  cur,
                            "base":     round(base_p, 2),
                            "discount": disc,
                            "currency": currency,
                        })

            # Deduplicate
            seen = set()
            unique = []
            for e in editions:
                if e["name"] not in seen:
                    seen.add(e["name"])
                    unique.append(e)

            self._editions = unique or [{
                "name":     "Standard Edition",
                "current":  self._game.price.current if self._game.price else 0,
                "base":     self._game.price.base    if self._game.price else 0,
                "discount": self._game.price.discount_pct if self._game.price else 0,
                "currency": self._game.price.currency if self._game.price else "USD",
            }]
            self._sig.editions_ready.emit(self._editions)
        except Exception as e:
            print(f"[MarkPurchased] {e}")
            self._sig.editions_ready.emit([])

    def _show_editions(self, editions: list):
        self._loading_lbl.setText(i18n.t("mark_purchased.select_edition"))
        self._loading_lbl.setStyleSheet(f"color:{COLORS['text_dim']}; background:transparent;")

        # Clear
        for i in reversed(range(self._ed_lay.count())):
            w = self._ed_lay.itemAt(i).widget()
            if w: w.deleteLater()

        for i, ed in enumerate(editions):
            self._make_edition_card(ed, selected=(i == 0))

        if editions:
            self._select_edition(editions[0])

    def _make_edition_card(self, ed: dict, selected=False):
        border = COLORS["blue"] if selected else COLORS["border"]
        card = QFrame()
        card._edition = ed
        card.setStyleSheet(f"""
            QFrame {{
                background:{COLORS['card']};
                border:{'2' if selected else '1'}px solid {border};
                border-radius:6px;
            }}
        """)
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        h = QHBoxLayout(card)
        h.setContentsMargins(10, 8, 10, 8)

        name_lbl = QLabel(ed["name"])
        name_lbl.setFont(QFont("Space Mono", 10, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color:{COLORS['text']}; border:none;")
        h.addWidget(name_lbl)
        h.addStretch()

        cur  = ed.get("current", 0)
        base = ed.get("base", 0)
        disc = ed.get("discount", 0)
        cur_lbl = QLabel(f"${cur:.2f}")
        cur_lbl.setFont(QFont("Space Mono", 11, QFont.Weight.Bold))
        cur_lbl.setStyleSheet(f"color:{COLORS['green'] if disc > 0 else COLORS['text']}; border:none;")
        h.addWidget(cur_lbl)

        if disc > 0:
            base_lbl = QLabel(f"${base:.2f}")
            base_lbl.setFont(QFont("Space Mono", 9))
            base_lbl.setStyleSheet(f"color:{COLORS['text_dim']}; border:none;")
            h.addWidget(base_lbl)

            disc_lbl = QLabel(f"-{disc}%")
            disc_lbl.setFont(QFont("Space Mono", 9))
            disc_lbl.setStyleSheet(f"color:{COLORS['green']}; border:none;")
            h.addWidget(disc_lbl)

        # Click
        def _click(e, ed=ed): self._select_edition(ed)
        card.mousePressEvent = _click

        self._ed_lay.addWidget(card)

    def _select_edition(self, ed: dict):
        self._selected_edition = ed
        self._price_edit.setText(f"{ed['current']:.2f}")
        self._base_edit.setText(f"{ed['base']:.2f}")
        # Update borders
        for i in range(self._ed_lay.count()):
            w = self._ed_lay.itemAt(i).widget()
            if w and hasattr(w, "_edition"):
                sel = w._edition["name"] == ed["name"]
                w.setStyleSheet(f"""
                    QFrame {{
                        background:{COLORS['card']};
                        border:{'2' if sel else '1'}px solid {COLORS['blue'] if sel else COLORS['border']};
                        border-radius:6px;
                    }}
                """)
        self._update_savings()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _update_savings(self):
        try:
            paid  = float(self._price_edit.text())
            base  = float(self._base_edit.text())
            saved = base - paid
            currency = self._game.price.currency if self._game.price else ""
            if saved > 0.01:
                pct = int(saved / base * 100) if base > 0 else 0
                self._savings_lbl.setText(
                    i18n.t("mark_purchased.saved_msg", amount=f"{saved:,.2f}", currency=currency, pct=pct))
                self._savings_lbl.setStyleSheet(
                    f"color:{COLORS['green']}; background:transparent;")
            else:
                self._savings_lbl.setText(i18n.t("mark_purchased.full_price_label"))
                self._savings_lbl.setStyleSheet(
                    f"color:{COLORS['text_dim']}; background:transparent;")
        except (ValueError, ZeroDivisionError):
            self._savings_lbl.setText("")

    def _confirm(self):
        try:
            paid     = float(self._price_edit.text())
            base     = float(self._base_edit.text())
            date     = self._date_edit.text().strip()
            edition  = (self._selected_edition.get("name")
                        or self._ed_lay.itemAt(0).widget()._edition["name"]
                        if self._ed_lay.count() else "Standard")
            currency = self._game.price.currency if self._game.price else "USD"
            disc_pct = max(0, int((1 - paid/base)*100)) if base > 0 else 0

            purchase = Purchase(
                app_id=self._game.app_id, name=self._game.name,
                purchased_at=date, price_paid=paid, base_price=base,
                currency=currency, discount_pct=disc_pct,
                edition=edition, saved=max(0.0, base - paid),
            )
            purchases.add(purchase)
            self._game.status = "Comprado"
            repo.update(self._game)
            self._on_success(purchase)
            self.accept()
        except ValueError:
            self._savings_lbl.setText(i18n.t("mark_purchased.invalid"))
            self._savings_lbl.setStyleSheet(f"color:{COLORS['red']}; background:transparent;")