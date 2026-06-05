"""AddGameDialog — PySide6."""
import threading
from typing import Callable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QWidget, QGridLayout, QTextEdit,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont

from config import COLORS, PRIORITY_OPTIONS, PRIORITY_COLORS
from data.models import Game
import data.repository as repo
import services.steam_api as steam
import services.steamgriddb as sgdb
import services.steamdb_scraper as steamdb
import i18n
from ui.settings_loader import get_settings

MAX_RESULTS = 5


def _lbl(text, size=10, bold=False, color=None):
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold: f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or COLORS['text']}; background-color:transparent;")
    return l


class _Sig(QObject):
    results_ready  = Signal(list)
    preview_ready  = Signal(dict, object, object)
    status_update  = Signal(str, str)


class AddGameDialog(QDialog):

    def __init__(self, parent, on_success: Callable, **kwargs):
        super().__init__(parent)
        self.on_success       = on_success
        self._fetched_data    = None
        self._fetched_price   = None
        self._fetched_history = None
        self._priority        = "B"
        self._sig             = _Sig()
        self._sig.results_ready.connect(self._show_results)
        self._sig.preview_ready.connect(self._update_preview)
        self._sig.status_update.connect(self._set_status)

        self.setWindowTitle(i18n.t("add_game.title"))
        self.setFixedSize(540, 580)
        self.setStyleSheet(f"QDialog {{ background:{COLORS['panel']}; }}")
        self._build()

    def _build(self):
        P = 18
        lay = QVBoxLayout(self)
        lay.setContentsMargins(P, 12, P, 12)
        lay.setSpacing(6)

        lay.addWidget(_lbl(i18n.t("add_game.title"), 13, bold=True))

        # Search row
        sr = QHBoxLayout()
        self._entry = QLineEdit()
        self._entry.setPlaceholderText(i18n.t("add_game.search_appid"))
        self._entry.setFixedHeight(32)
        self._entry.setStyleSheet(f"""
            QLineEdit {{ background:{COLORS['card']}; color:{COLORS['text']};
                border:1px solid {COLORS['border']}; border-radius:6px;
                padding:0 8px; font-family:'Space Mono'; font-size:11px; }}
            QLineEdit:focus {{ border-color:{COLORS['blue']}; }}
        """)
        self._entry.returnPressed.connect(self._search)
        sr.addWidget(self._entry, 1)

        search_btn = QPushButton(i18n.t("add_game.search_btn"))
        search_btn.setFixedSize(72, 32)
        search_btn.setStyleSheet(f"""
            QPushButton {{ background:{COLORS['blue']}; color:#0a1929;
                border:none; border-radius:6px;
                font-family:'Space Mono'; font-size:11px; font-weight:bold; }}
            QPushButton:hover {{ background:#4fa8d8; }}
            QPushButton:disabled {{ background:{COLORS['border']}; color:{COLORS['text_dim']}; }}
        """)
        search_btn.clicked.connect(self._search)
        self._search_btn = search_btn
        sr.addWidget(search_btn)
        lay.addLayout(sr)

        self._status_lbl = _lbl(i18n.t("add_game.hint"), 10, color=COLORS["text_dim"])
        lay.addWidget(self._status_lbl)

        lay.addWidget(_lbl(i18n.t("add_game.section_results"), 9, bold=True,
                           color=COLORS["text_dim"]))

        # Results box
        results_box = QFrame()
        results_box.setStyleSheet(f"""
            QFrame {{ background:{COLORS['card']};
                border:1px solid {COLORS['border']}; border-radius:8px; }}
        """)
        rb_lay = QVBoxLayout(results_box)
        rb_lay.setContentsMargins(0, 0, 0, 0)
        rb_lay.setSpacing(0)

        self._rows: list[dict] = []
        for i in range(MAX_RESULTS):
            if i > 0:
                div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
                div.setStyleSheet(f"color:{COLORS['border']};"); div.setFixedHeight(1)
                rb_lay.addWidget(div)

            row_w = QWidget()
            row_w.setFixedHeight(30)
            row_w.setStyleSheet("background:transparent;")
            row_w.setCursor(Qt.CursorShape.PointingHandCursor)
            rl = QHBoxLayout(row_w)
            rl.setContentsMargins(8, 0, 8, 0)

            id_lbl   = _lbl("", 10, color=COLORS["text_dim"])
            id_lbl.setFixedWidth(64)
            name_lbl = _lbl("", 11, color=COLORS["text_dim"])
            price_lbl = _lbl("", 10, color=COLORS["text_dim"])
            price_lbl.setFixedWidth(86)
            price_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            rl.addWidget(id_lbl)
            rl.addWidget(name_lbl, 1)
            rl.addWidget(price_lbl)

            row_data = {"widget": row_w, "id_lbl": id_lbl,
                        "name_lbl": name_lbl, "price_lbl": price_lbl, "data": None}
            row_w.mousePressEvent = lambda e, rd=row_data: self._select_row(rd)

            def _enter(e, rw=row_w, rd=row_data):
                if rd["data"]: rw.setStyleSheet(f"background:{COLORS['card_hover']};")
            def _leave(e, rw=row_w, rd=row_data):
                if rd["data"]: rw.setStyleSheet("background:transparent;")
            row_w.enterEvent = _enter
            row_w.leaveEvent = _leave

            rb_lay.addWidget(row_w)
            self._rows.append(row_data)

        lay.addWidget(results_box)

        lay.addWidget(_lbl(i18n.t("add_game.section_preview"), 9, bold=True,
                           color=COLORS["text_dim"]))

        # Preview grid
        prev = QFrame()
        prev.setStyleSheet(f"""
            QFrame {{ background:{COLORS['card']};
                border:1px solid {COLORS['border']}; border-radius:8px; }}
        """)
        pg = QGridLayout(prev)
        pg.setContentsMargins(10, 5, 10, 5)
        pg.setSpacing(2)

        self._prev_labels: dict[str, QLabel] = {}
        defs = [
            ("name",    i18n.t("game.name")),
            ("genre",   i18n.t("game.genre")),
            ("year",    i18n.t("game.year")),
            ("dev",     i18n.t("game.developer")),
            ("price",   i18n.t("game.price_current")),
            ("history", i18n.t("game.price_low")),
        ]
        for idx, (key, label) in enumerate(defs):
            c = (idx % 2) * 2
            r = idx // 2
            pg.addWidget(_lbl(f"{label}:", 10, color=COLORS["text_dim"]), r, c)
            val = _lbl("—", 10)
            pg.addWidget(val, r, c + 1)
            self._prev_labels[key] = val

        lay.addWidget(prev)

        # Priority + Notes
        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        prio_col = QVBoxLayout()
        prio_col.addWidget(_lbl(i18n.t("game.priority"), 11, bold=True))
        p_row = QHBoxLayout()
        p_row.setSpacing(4)
        for p in PRIORITY_OPTIONS:
            color = PRIORITY_COLORS.get(p, "#666")
            btn = QPushButton(p)
            btn.setFixedSize(38, 28)
            active = p == "B"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:{"transparent" if not active else color};
                    color:#fff; border:1px solid {color}; border-radius:5px;
                    font-family:'Space Mono'; font-size:11px; font-weight:bold;
                }}
                QPushButton:hover {{ background:{color}; }}
            """)
            btn.clicked.connect(lambda _, pv=p: self._set_priority(pv))
            self.__dict__[f"_pb_{p}"] = btn
            p_row.addWidget(btn)
        p_row.addStretch()
        prio_col.addLayout(p_row)
        prio_col.addStretch()
        bottom.addLayout(prio_col)

        notes_col = QVBoxLayout()
        notes_col.addWidget(_lbl(i18n.t("game.notes"), 11, bold=True))
        self._notes = QTextEdit()
        self._notes.setFixedHeight(56)
        self._notes.setStyleSheet(f"""
            QTextEdit {{ background:{COLORS['card']}; color:{COLORS['text']};
                border:1px solid {COLORS['border']}; border-radius:4px;
                font-family:'Space Mono'; font-size:10px; padding:4px; }}
        """)
        notes_col.addWidget(self._notes)
        bottom.addLayout(notes_col, 1)
        lay.addLayout(bottom)

        # Buttons
        btn_row = QHBoxLayout()
        cancel = QPushButton(i18n.t("actions.cancel"))
        cancel.setFixedSize(82, 32)
        cancel.clicked.connect(self.reject)
        cancel.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{COLORS['text_dim']};
                border:1px solid {COLORS['border']}; border-radius:6px;
                font-family:'Space Mono'; font-size:11px; }}
            QPushButton:hover {{ background:{COLORS['card_hover']}; }}
        """)
        btn_row.addWidget(cancel)
        btn_row.addStretch()

        self._save_btn = QPushButton(i18n.t("actions.save"))
        self._save_btn.setFixedSize(110, 32)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save)
        self._save_btn.setStyleSheet(f"""
            QPushButton {{ background:{COLORS['blue']}; color:#0a1929;
                border:none; border-radius:6px;
                font-family:'Space Mono'; font-size:12px; font-weight:bold; }}
            QPushButton:hover {{ background:#4fa8d8; }}
            QPushButton:disabled {{ background:{COLORS['border']}; color:{COLORS['text_dim']}; }}
        """)
        btn_row.addWidget(self._save_btn)
        lay.addLayout(btn_row)

        self._entry.setFocus()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _set_status(self, text: str, color: str):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(f"color:{color}; background:transparent;")

    def _select_row(self, rd: dict):
        if not rd["data"]: return
        r = rd["data"]
        for row in self._rows:
            sel = row is rd
            row["widget"].setStyleSheet(
                f"background:{COLORS['card_hover']};" if sel and row["data"]
                else "background:transparent;")
            if row["data"]:
                row["name_lbl"].setStyleSheet(
                    f"color:{COLORS['blue']}; background:transparent; font-weight:bold;"
                    if sel else f"color:{COLORS['text']}; background:transparent;")
        self._sig.status_update.emit(
            i18n.t("add_game.selected", name=r["name"]), COLORS["blue"])
        self._fetch_details(r["id"])

    def _populate_rows(self, results: list):
        for i, rd in enumerate(self._rows):
            if i < len(results):
                r = results[i]
                rd["data"] = r
                rd["id_lbl"].setText(f"#{r['id']}")
                rd["id_lbl"].setStyleSheet(f"color:{COLORS['text_dim']}; background:transparent;")
                rd["name_lbl"].setText(r["name"])
                rd["name_lbl"].setStyleSheet(f"color:{COLORS['text']}; background:transparent;")
                price = r.get("price", 0)
                if price is not None:
                    pt = (f"${price:,.0f}" if price > 0
                          else i18n.t("add_game.free"))
                    col = COLORS["green"] if price > 0 else COLORS["blue"]
                    rd["price_lbl"].setText(pt)
                    rd["price_lbl"].setStyleSheet(f"color:{col}; background:transparent;")
                else:
                    rd["price_lbl"].setText("")
            else:
                rd["data"] = None
                rd["id_lbl"].setText("")
                rd["name_lbl"].setText("")
                rd["name_lbl"].setStyleSheet(f"color:{COLORS['text_dim']}; background:transparent;")
                rd["price_lbl"].setText("")

    def _search(self):
        query = self._entry.text().strip()
        if not query: return
        if query.isdigit():
            self._sig.status_update.emit(i18n.t("add_game.fetching"), COLORS["text_dim"])
            self._fetch_details(query)
            return
        self._sig.status_update.emit(i18n.t("add_game.searching"), COLORS["text_dim"])
        self._search_btn.setEnabled(False)
        self._save_btn.setEnabled(False)
        self._fetched_data = None
        self._populate_rows([])

        def _do():
            settings = get_settings()
            results = steam.search_games(query, limit=MAX_RESULTS,
                                         cc=settings.get("country", "mx"))
            self._sig.results_ready.emit(results)

        threading.Thread(target=_do, daemon=True).start()

    def _show_results(self, results: list):
        self._search_btn.setEnabled(True)
        if not results:
            self._sig.status_update.emit(
                i18n.t("add_game.error_not_found"), COLORS["red"])
            return
        self._populate_rows(results)
        self._sig.status_update.emit(
            i18n.t("add_game.select_hint", n=len(results)), COLORS["text_dim"])

    def _fetch_details(self, app_id: str):
        def _work():
            if repo.exists(app_id):
                existing = repo.get_by_app_id(app_id)
                name = existing.name if existing else app_id
                self._sig.status_update.emit(
                    f"'{name}' is already in your wishlist", COLORS["gold"])
                return
            settings = get_settings()
            data = steam.get_app_details(app_id, country=settings.get("country", "mx"))
            if not data:
                self._sig.status_update.emit(i18n.t("add_game.error_api"), COLORS["red"])
                return
            meta  = steam.parse_metadata(data)
            meta["app_id"] = app_id
            price = steam.parse_price(data)
            hist  = steamdb.get_price_history(app_id)
            self._fetched_data    = meta
            self._fetched_price   = price
            self._fetched_history = hist
            self._sig.preview_ready.emit(meta, price, hist)

        threading.Thread(target=_work, daemon=True).start()

    def _update_preview(self, meta, price, history):
        self._prev_labels["name"].setText(meta.get("name", "—"))
        self._prev_labels["genre"].setText(meta.get("genre", "—"))
        self._prev_labels["year"].setText(str(meta.get("release_year") or "—"))
        self._prev_labels["dev"].setText(meta.get("developer", "—"))
        if price:
            pt = f"${price.current:,.0f} {price.currency}"
            if price.discount_pct:
                pt += f" (-{price.discount_pct}%)"
            col = COLORS["green"] if price.is_on_sale else COLORS["text"]
            self._prev_labels["price"].setText(pt)
            self._prev_labels["price"].setStyleSheet(
                f"color:{col}; background:transparent;")
        if history and history.all_time_low:
            ht = f"${history.all_time_low:,.0f}"
            if history.all_time_low_date:
                ht += f" · {history.all_time_low_date}"
            self._prev_labels["history"].setText(ht)
            self._prev_labels["history"].setStyleSheet(
                f"color:{COLORS['blue']}; background:transparent;")
        self._sig.status_update.emit(i18n.t("add_game.data_ok"), COLORS["green"])
        self._save_btn.setEnabled(True)

    def _set_priority(self, p: str):
        self._priority = p
        for pr in PRIORITY_OPTIONS:
            color = PRIORITY_COLORS.get(pr, "#666")
            btn   = self.__dict__.get(f"_pb_{pr}")
            if btn:
                active = pr == p
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background:{"transparent" if not active else color};
                        color:#fff; border:1px solid {color}; border-radius:5px;
                        font-family:'Space Mono'; font-size:11px; font-weight:bold;
                    }}
                    QPushButton:hover {{ background:{color}; }}
                """)

    def _save(self):
        if not self._fetched_data: return
        meta  = self._fetched_data
        notes = self._notes.toPlainText().strip()
        game  = Game(
            id=0, name=meta.get("name", ""),
            app_id=meta.get("app_id", ""),
            steam_url=meta.get("steam_url", ""),
            genre=meta.get("genre", ""),
            release_year=meta.get("release_year", 0),
            developer=meta.get("developer", ""),
            publisher=meta.get("publisher", ""),
            categories=meta.get("categories", ""),
            short_description=meta.get("short_description", ""),
            priority=self._priority,
            status="Wishlist",
            price=self._fetched_price,
            price_history=self._fetched_history,
            notes=notes,
        )
        repo.add(game)
        settings = get_settings()
        api_key  = settings.get("steamgriddb_key", "")

        def _dl():
            cover = sgdb.download_cover(game.app_id, api_key, game.name)
            if cover:
                game.cover_path = cover
                repo.update(game)
        threading.Thread(target=_dl, daemon=True).start()

        self.on_success()
        self.accept()