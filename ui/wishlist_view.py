from __future__ import annotations
import threading
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QScrollArea,
    QGridLayout, QSizePolicy, QApplication,
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSize
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont

import i18n
from ui.library_view import translate_genre
import data.repository as repo
from data.models import Game
from data.status import STATUS_PURCHASED, normalize_status
from config import COLORS, PRIORITY_COLORS, PRIORITY_OPTIONS
from ui.widgets import SteamButton, StatCard, SectionHeader

COLS     = 6
MAX_ROWS = 100
CARD_W   = 148
IMG_H    = 200


# ── Signal bridge ─────────────────────────────────────────────────────────────

class _Bridge(QObject):
    images_ready = Signal(list)   # list of (card, QPixmap)
    layout_done  = Signal()


# ── Game card ─────────────────────────────────────────────────────────────────

class _GameCard(QFrame):
    CARD_W = CARD_W
    IMG_H  = IMG_H

    def __init__(self, parent=None, on_click: Callable = None):
        super().__init__(parent)
        self._on_click  = on_click
        self._game: Optional[Game] = None
        self._visible   = False
        self.setFixedWidth(CARD_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()

    def _build(self):
        self.setStyleSheet(f"""
            _GameCard {{
                background: {COLORS['card']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
            _GameCard:hover {{
                border-color: {COLORS['blue']}88;
                background: {COLORS['card_hover']};
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 6)
        lay.setSpacing(0)

        # Cover image
        self._img_lbl = QLabel()
        self._img_lbl.setFixedSize(CARD_W - 4, IMG_H)
        self._img_lbl.setObjectName("CardImg")
        self._img_lbl.setStyleSheet(f"QLabel#CardImg {{ background:{COLORS['card_hover']}; border-radius:6px; }}")
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._img_lbl)

        # Priority badge overlay
        self._badge = QLabel(self._img_lbl)
        self._badge.setFixedSize(24, 24)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFont(QFont("Space Mono", 10, QFont.Weight.Bold))
        self._badge.move(CARD_W - 4 - 28, 4)
        self._badge.setAutoFillBackground(False)
        self._badge.setStyleSheet("border-radius:4px; color:#000;")
        self._badge.hide()

        # Info
        info = QWidget()
        info.setAutoFillBackground(False)
        info_lay = QVBoxLayout(info)
        info_lay.setContentsMargins(6, 4, 6, 0)
        info_lay.setSpacing(1)

        self._name_lbl = QLabel()
        self._name_lbl.setFont(QFont("Space Mono", 9, QFont.Weight.Bold))
        self._name_lbl.setStyleSheet(f"color:{COLORS['text']}; background-color:transparent;")
        self._name_lbl.setAutoFillBackground(False)
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setMaximumWidth(CARD_W - 12)
        info_lay.addWidget(self._name_lbl)

        self._meta_lbl = QLabel()
        self._meta_lbl.setFont(QFont("Space Mono", 8))
        self._meta_lbl.setStyleSheet(f"color:{COLORS['text_dim']}; background-color:transparent;")
        self._meta_lbl.setAutoFillBackground(False)
        info_lay.addWidget(self._meta_lbl)

        pr_row = QHBoxLayout()
        pr_row.setSpacing(4)
        self._price_lbl = QLabel()
        self._price_lbl.setFont(QFont("Space Mono", 9, QFont.Weight.Bold))
        self._price_lbl.setStyleSheet(f"color:{COLORS['text']}; background-color:transparent;")
        self._price_lbl.setAutoFillBackground(False)
        pr_row.addWidget(self._price_lbl)

        self._dot_lbl = QLabel()
        self._dot_lbl.setFont(QFont("Space Mono", 9, QFont.Weight.Bold))
        self._dot_lbl.setAutoFillBackground(False)
        pr_row.addStretch()
        pr_row.addWidget(self._dot_lbl)
        info_lay.addLayout(pr_row)

        lay.addWidget(info)

    def mousePressEvent(self, event):
        if self._game and self._on_click:
            self._on_click(self._game)

    def show_game(self, game: Game):
        self._game    = game
        self._visible = True

        # Reset cover to placeholder
        self._img_lbl.setPixmap(QPixmap())
        self._img_lbl.setStyleSheet(
            f"background:{COLORS['card_hover']}; border-radius:6px;")

        # Badge
        p = game.priority or "C"
        color = PRIORITY_COLORS.get(p, COLORS["border"])
        self._badge.setText(p)
        self._badge.setStyleSheet(
            f"background:{color}; border-radius:4px; color:#000;")
        self._badge.show()

        # Name
        self._name_lbl.setText(game.name or "")

        # Meta
        _genre = translate_genre(game.genre.split(',')[0].strip()) if game.genre else '—'
        meta = f"{game.release_year or '—'} · {_genre}"
        self._meta_lbl.setText(meta)

        # Price
        if game.price:
            col = COLORS["green"] if game.price.is_on_sale else COLORS["text"]
            self._price_lbl.setText(f"${game.price.current:,.0f}")
            self._price_lbl.setStyleSheet(f"color:{col}; background-color:transparent;")
        else:
            self._price_lbl.setText("—")
            self._price_lbl.setStyleSheet(f"color:{COLORS['text_dim']}; background-color:transparent;")

        # Rec dot
        rec = game.buy_recommendation
        if any(x in rec for x in (i18n.t("recommendation.buy_now"), i18n.t("recommendation.near_low"))):
            dot, dot_c = "✓", COLORS["green"]
        elif i18n.t("recommendation.near_low") in rec:
            dot, dot_c = "≈", COLORS["gold"]
        else:
            dot, dot_c = "↓", COLORS["text_dim"]
        self._dot_lbl.setText(dot)
        self._dot_lbl.setStyleSheet(f"color:{dot_c}; background-color:transparent;")

        self.show()

    def hide_card(self):
        self._game    = None
        self._visible = False
        self.hide()

    def set_image(self, pixmap: QPixmap):
        if self._visible and self._game and pixmap:
            scaled = pixmap.scaled(
                CARD_W - 4, IMG_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setStyleSheet("border-radius:6px;")


# ── Wishlist view ─────────────────────────────────────────────────────────────

class WishlistView(QFrame):

    def __init__(self, parent=None,
                 on_game_click: Callable = None,
                 on_add_game:   Callable = None,
                 **kwargs):
        super().__init__(parent)
        self.on_game_click = on_game_click
        self.on_add_game   = on_add_game

        self._games: list[Game]       = []
        self._filter                  = "all"
        self._search_text             = ""
        self._last_rendered_ids: list = []
        self._pool: dict[str, list]   = {}
        self._row_widgets: list[QWidget] = []
        self._filter_timer            = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)
        self._filter_timer.timeout.connect(self._apply_filter)

        self._bridge = _Bridge()
        self._bridge.images_ready.connect(self._apply_images)

        self.setStyleSheet(f"background:{COLORS['bg']};")
        self._build()
        self._init_pool()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ───────────────────────────────────────────────
        topbar = QFrame()
        topbar.setFixedHeight(52)
        topbar.setStyleSheet(f"background:{COLORS['panel']}; border:none;")
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(18, 0, 8, 0)
        tb.setSpacing(8)

        title = QLabel(i18n.t("nav.wishlist"))
        title.setFont(QFont("Space Mono", 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{COLORS['text']}; background-color:transparent;")
        tb.addWidget(title)

        self._search = QLineEdit()
        self._search.setPlaceholderText(i18n.t("actions.search"))
        self._search.setFixedSize(200, 30)
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background:{COLORS['card']}; color:{COLORS['text']};
                border:1px solid {COLORS['border']}; border-radius:6px;
                padding: 0 8px; font-family:'Space Mono'; font-size:11px;
            }}
        """)
        self._search.textChanged.connect(self._on_search)
        tb.addWidget(self._search)

        # Filter buttons
        self._filter_btns: dict[str, QPushButton] = {}
        for key, lbl in [("all", i18n.t("filters.all")),
                          ("S","S"),("A","A"),("B","B"),("C","C"),
                          ("sale", i18n.t("filters.on_sale")),
                          ("purchased", i18n.t("filters.purchased"))]:
            btn = QPushButton(lbl)
            btn.setFixedHeight(28)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setStyleSheet(self._filter_btn_style(key == "all"))
            btn.clicked.connect(lambda _, k=key: self._set_filter(k))
            tb.addWidget(btn)
            self._filter_btns[key] = btn

        tb.addStretch()

        self._covers_lbl = QLabel("")
        self._covers_lbl.setStyleSheet(f"color:{COLORS['text_dim']}; background-color:transparent; font-size:10px;")
        tb.addWidget(self._covers_lbl)

        covers_btn = SteamButton(text=i18n.t("wishlist.covers_btn"), command=self._download_covers,
                                 style="ghost")
        covers_btn.setFixedHeight(30)
        tb.addWidget(covers_btn)
        self._covers_btn = covers_btn

        prices_btn = SteamButton(text=i18n.t("wishlist.refresh_prices_btn"),
                                 command=self._refresh_all_prices, style="ghost")
        prices_btn.setFixedHeight(30)
        tb.addWidget(prices_btn)
        self._prices_btn = prices_btn

        export_btn = SteamButton(text=i18n.t("actions.export"),
                                 command=self._export_excel, style="ghost")
        export_btn.setFixedHeight(30)
        tb.addWidget(export_btn)

        add_btn = SteamButton(text=f"+ {i18n.t('actions.add')}",
                              command=self.on_add_game, style="primary")
        add_btn.setFixedHeight(30)
        tb.addWidget(add_btn)

        root.addWidget(topbar)

        # ── Stats row ─────────────────────────────────────────────
        stats_row = QFrame()
        stats_row.setStyleSheet(f"background:{COLORS['bg']}; border:none;")
        sr = QHBoxLayout(stats_row)
        sr.setContentsMargins(14, 10, 14, 0)
        sr.setSpacing(6)

        self._stats: dict[str, StatCard] = {}
        for key, label, icon, accent in [
            ("total",   i18n.t("stats.total_games"), "◈", COLORS["blue"]),
            ("value",   i18n.t("stats.total_value"),  "◎", "#94a3b8"),
            ("savings", i18n.t("stats.savings"),      "↓", COLORS["green"]),
            ("s_count", i18n.t("stats.priority_s"),   "★", COLORS["gold"]),
            ("on_sale", i18n.t("stats.on_sale_now"),  "⚡", "#f472b6"),
        ]:
            card = StatCard(label=label, value="—", icon=icon, accent=accent)
            card.setMinimumHeight(68)
            sr.addWidget(card)
            self._stats[key] = card

        root.addWidget(stats_row)

        # ── Scroll area ───────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ border:none; background:{COLORS['bg']}; }}
            QScrollBar:vertical {{
                background:{COLORS['bg']}; width:6px; border:none;
            }}
            QScrollBar::handle:vertical {{
                background:{COLORS['border']}; border-radius:3px; min-height:30px;
            }}
            QScrollBar::handle:vertical:hover {{ background:{COLORS['blue']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)

        self._content = QWidget()
        self._content.setStyleSheet(f"background:{COLORS['bg']};")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(14, 10, 14, 10)
        self._content_lay.setSpacing(0)
        self._content_lay.addStretch()

        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll, 1)

        # Empty label
        self._empty_lbl = QLabel(i18n.t("wishlist.no_match"))
        self._empty_lbl.setFont(QFont("Space Mono", 13))
        self._empty_lbl.setStyleSheet(f"color:{COLORS['text_dim']}; background-color:transparent;")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.hide()
        self._content_lay.insertWidget(0, self._empty_lbl)

    def _filter_btn_style(self, active: bool) -> str:
        bg  = COLORS["blue"] if active else "transparent"
        fg  = "#000" if active else COLORS["text_dim"]
        return f"""
            QPushButton {{
                background:{bg}; color:{fg};
                border:1px solid {COLORS['border']};
                border-radius:5px; font-family:'Space Mono';
                font-size:11px; padding:2px 8px; min-height:28px;
            }}
            QPushButton:hover {{ background:{COLORS['card_hover']}; color:{COLORS['text']}; }}
        """

    # ── Card pool ─────────────────────────────────────────────────────────────

    def _init_pool(self):
        """Pre-create card pool for all priorities."""
        for p in ("S", "A", "B", "C"):
            cards = []
            for _ in range(MAX_ROWS * COLS):
                card = _GameCard(on_click=self.on_game_click)
                card.hide_card()
                cards.append(card)
            self._pool[p] = cards

    # ── Data ──────────────────────────────────────────────────────────────────

    def refresh(self, force: bool = False):
        self._games = repo.get_all()
        print("Wishlist refreshed")
        print(f"Games loaded: {len(self._games)}")
        self._update_stats()
        # Include status and len so any add/remove/status-change forces re-render.
        # status is included so "Purchased" games that change status also update.
        new_ids = [(g.id, g.priority, g.status, g.cover_path,
                    g.price.current if g.price else 0) for g in self._games]
        if force or new_ids != self._last_rendered_ids:
            self._last_rendered_ids = new_ids
            # Always run _apply_filter on main thread.
            # If we're already on the main thread this is a direct call;
            # if called from a background thread the QTimer ensures safety.
            QTimer.singleShot(0, self._apply_filter)

    def reload_after_change(self):
        """
        Call this after any action that adds, removes, or changes a game
        (Add Game, Import Wishlist, Mark Purchased, Mark Wishlist, Delete
        Game, Change Priority). Forces a full re-fetch from the repository
        and an immediate re-render, regardless of whether the cached
        "rendered ids" snapshot looks unchanged.
        """
        self._last_rendered_ids = []
        self.refresh(force=True)

    def _update_stats(self):
        games    = self._games
        total    = len(games)
        on_sale  = sum(1 for g in games if g.price and g.price.is_on_sale)
        s_count  = sum(1 for g in games if g.priority == "S")
        currency = next((g.price.currency for g in games if g.price), "")
        total_v  = sum(g.price.current for g in games if g.price)
        savings  = sum(g.price.base - g.price.current
                       for g in games
                       if g.price and g.price.is_on_sale
                       and g.price.base > g.price.current)
        self._stats["total"].set_value(str(total))
        self._stats["value"].set_value(
            f"${total_v:,.0f}{' '+currency if currency else ''}")
        self._stats["savings"].set_value(f"${savings:,.0f}")
        self._stats["s_count"].set_value(str(s_count))
        self._stats["on_sale"].set_value(str(on_sale))

    # ── Filter ────────────────────────────────────────────────────────────────

    def _on_search(self, text: str):
        self._search_text = text.lower()
        self._filter_timer.start()

    def _set_filter(self, key: str):
        self._filter = key
        for k, btn in self._filter_btns.items():
            active = k == key
            btn.setChecked(active)
            btn.setStyleSheet(self._filter_btn_style(active))
        self._apply_filter()

    # Status comparisons now go through data.status.normalize_status() —
    # see that module for why we never compare g.status to a literal string.

    def _apply_filter(self):
        if self._filter == "purchased":
            # Show ONLY purchased games — the inverse of the main wishlist grid.
            # normalize_status() maps legacy/translated status strings (from
            # older app versions) back to the canonical STATUS_PURCHASED, so
            # those games still appear here instead of vanishing entirely.
            games = [g for g in self._games
                     if normalize_status(g.status) == STATUS_PURCHASED]
        else:
            # Exclude purchased games from the main grid. Anything that
            # normalizes to a non-purchased status — including unrecognized
            # or corrupted status strings, which normalize_status() defaults
            # to Wishlist rather than silently dropping — is shown here.
            games = [g for g in self._games
                     if normalize_status(g.status) != STATUS_PURCHASED]
            if self._filter == "sale":
                games = [g for g in games if g.price and g.price.is_on_sale]
            elif self._filter in ("S","A","B","C"):
                games = [g for g in games if g.priority == self._filter]
        if self._search_text:
            q = self._search_text
            games = [g for g in games
                     if q in g.name.lower() or q in g.genre.lower()]
        self._layout(games)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _layout(self, games: list[Game]):
        """Assign games to card pool — no widget creation."""
        has_any = bool(games)
        self._empty_lbl.setVisible(not has_any)

        images_to_load: list = []

        # Hide all cards and detach them from their current row widget.
        # Must happen BEFORE deleting old row widgets below, since the cards
        # are pooled/reused across layouts — if we deleteLater() a row while
        # a pooled card is still its child, Qt destroys the card with it.
        for p_cards in self._pool.values():
            for card in p_cards:
                card.hide_card()
                card.setParent(None)

        # Remove + fully delete row widgets created by the previous _layout()
        # call. Previously these were left orphaned in _content_lay, causing
        # stale rows, leftover/duplicate cards, and games that wouldn't
        # appear/disappear without an app restart.
        for row in self._row_widgets:
            self._content_lay.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._row_widgets = []

        # Clear old section widgets
        for attr in [f"_sec_{p}" for p in "SABC"]:
            if hasattr(self, attr):
                w = getattr(self, attr)
                self._content_lay.removeWidget(w)
                w.hide()

        insert_pos = 1  # after empty_lbl

        for priority in ("S", "A", "B", "C"):
            group = [g for g in games if g.priority == priority]
            if not group:
                continue

            # Section header
            attr = f"_sec_{priority}"
            if not hasattr(self, attr):
                lbl = QLabel(i18n.t(f"priority.{priority}"))
                lbl.setFont(QFont("Space Mono", 11, QFont.Weight.Bold))
                color = PRIORITY_COLORS.get(priority, COLORS["text_dim"])
                lbl.setStyleSheet(
                    f"color:{color}; padding:8px 0 4px 0; background-color:transparent;")
                setattr(self, attr, lbl)
            sec_lbl = getattr(self, attr)
            self._content_lay.insertWidget(insert_pos, sec_lbl)
            sec_lbl.show()
            insert_pos += 1

            # Grid rows
            pool    = self._pool[priority]
            pool_i  = 0
            row_w   = None

            for gi, game in enumerate(group[:MAX_ROWS * COLS]):
                col = gi % COLS
                if col == 0:
                    row_w = QWidget()
                    row_w.setAutoFillBackground(False)
                    row_lay = QHBoxLayout(row_w)
                    row_lay.setContentsMargins(0, 0, 0, 4)
                    row_lay.setSpacing(8)
                    row_lay.setAlignment(Qt.AlignmentFlag.AlignLeft)
                    self._content_lay.insertWidget(insert_pos, row_w)
                    self._row_widgets.append(row_w)
                    insert_pos += 1

                if pool_i < len(pool):
                    card = pool[pool_i]
                    pool_i += 1
                    card.setParent(row_w)
                    row_w.layout().addWidget(card)
                    card.show_game(game)
                    if game.cover_path:
                        images_to_load.append((card, game.cover_path))

            # Always add stretch to last row so cards align left
            if row_w and group:
                row_w.layout().addStretch(1)

        # Load images in background
        if images_to_load:
            QTimer.singleShot(10, lambda imgs=images_to_load:
                              self._load_images_bg(imgs))

    def _load_images_bg(self, items: list):
        """Load cover images in background thread, update on main thread."""
        def _work():
            results = []
            for card, path in items:
                try:
                    from pathlib import Path as _P
                    if path and _P(path).exists():
                        px = QPixmap(path)
                        if not px.isNull():
                            results.append((card, px))
                except Exception:
                    pass
            if results:
                self._bridge.images_ready.emit(results)

        threading.Thread(target=_work, daemon=True).start()

    def _apply_images(self, results: list):
        for card, pixmap in results:
            card.set_image(pixmap)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _download_covers(self):
        from services.steamgriddb import download_all_missing, cover_exists
        from ui.settings_loader import get_settings
        # Re-pull from the repository before counting "missing" — self._games
        # can be stale if games were added/synced from another view (e.g.
        # the Settings wishlist sync) since this view was last refreshed.
        self._games = repo.get_all()
        settings = get_settings()
        missing  = sum(1 for g in self._games if not cover_exists(g.app_id))
        if missing == 0:
            self._covers_lbl.setText(i18n.t("wishlist.covers_all_done"))
            self._covers_lbl.setStyleSheet(f"color:{COLORS['green']}; background-color:transparent; font-size:10px;")
            QTimer.singleShot(3000, lambda: self._covers_lbl.setText(""))
            return
        self._covers_btn.setEnabled(False)
        self._covers_lbl.setText(f"0/{missing}")

        def _prog(cur, tot, _name):
            QTimer.singleShot(0, lambda c=cur,t=tot:
                self._covers_lbl.setText(f"{c}/{t}"))

        def _done(dl, fail):
            def _upd():
                self._covers_btn.setEnabled(True)
                self._covers_lbl.setText(
                    i18n.t("wishlist.covers_ok").format(dl=dl) if not fail else i18n.t("wishlist.covers_result").format(dl=dl, fail=fail))
                from ui.image_cache import clear
                clear()
                self._last_rendered_ids = []
                self.refresh()
                QTimer.singleShot(4000, lambda: self._covers_lbl.setText(""))
            QTimer.singleShot(0, _upd)

        download_all_missing(
            self._games, settings.get("steamgriddb_key",""),
            on_progress=_prog, on_done=_done, max_workers=4,
        )

    def _refresh_all_prices(self):
        from services.steam_api import bulk_refresh_prices
        from ui.settings_loader import get_settings
        # Always re-pull from disk first — same staleness concern as covers.
        self._games = repo.get_all()
        settings = get_settings()
        country  = settings.get("country", "mx")
        total    = len(self._games)
        if total == 0:
            return

        self._prices_btn.setEnabled(False)
        self._covers_lbl.setText(f"0/{total}")

        def _prog(cur, tot, _name):
            QTimer.singleShot(0, lambda c=cur, t=tot:
                self._covers_lbl.setText(f"{c}/{t}"))

        def _done(updated, unchanged, failed):
            def _upd():
                self._prices_btn.setEnabled(True)
                self._covers_lbl.setText(
                    i18n.t("wishlist.prices_updated").format(n=updated)
                    if not failed else
                    i18n.t("wishlist.prices_updated_with_errors").format(n=updated, fail=failed))
                self._last_rendered_ids = []
                self.refresh(force=True)
                QTimer.singleShot(4000, lambda: self._covers_lbl.setText(""))
            QTimer.singleShot(0, _upd)

        bulk_refresh_prices(
            self._games, country=country,
            on_progress=_prog, on_done=_done, max_workers=6,
        )

    def _export_excel(self):
        import threading
        from data.excel_manager import export_excel
        threading.Thread(target=export_excel, daemon=True).start()