"""
Library — your Steam collection (owned games, playtime, recent activity)
plus what the curator tracks (wishlist, purchases, play status).

    LibraryView(parent)
    view.refresh(force=False)     force=True drops the Steam API cache first
    view.retranslate()            update visible strings in place

Steam stats come from services.library_api.get_library_stats() through
run_async. While loading the section shows Skeleton tiles; a LibraryError
becomes an EmptyState with the user-facing reason and an "Open settings"
button. Curator numbers come straight from the repositories (cached, cheap).

This module also hosts translate_genre / translate_genres, which other views
import.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QProgressBar, QWidget

import i18n
import data.purchase_repository as purchases
import data.repository as repo
from data.models import Game
from data.status import STATUS_ARCHIVED, STATUS_PURCHASED, STATUS_WISHLIST, normalize_status
from ui.animations import clear_layout
from ui.async_bridge import run_async
from ui.components import (Button, Card, EmptyState, ListRow, Pill, PriorityBadge, SectionHeader,
                           Skeleton, StatCard, SubHeader, hbox, label, scroll_area, vbox)
from ui.format import money, pct
from ui.theme import C, SP

PLAY_STATUSES = ["", "playing", "completed", "on_hold", "abandoned"]
PLAY_STATUS_STYLE = {          # key -> (icon, StatCard tone)
    "playing":   ("play", "accent"),
    "completed": ("check", "green"),
    "on_hold":   ("pause", "gold"),
    "abandoned": ("x", "pink"),
}
_TOP_N = 10
_BAR_WIDTH = 110


# ── Genre translation ─────────────────────────────────────────────────────────
# Steam delivers genre strings in the OS language (e.g. "Acción" on Spanish OS).
# We normalize them to English keys and translate via i18n.
# Unknown genres are shown as-is (untranslated).

_GENRE_NORMALIZE: dict[str, str] = {
    # English
    "action": "action", "adventure": "adventure", "rpg": "rpg",
    "strategy": "strategy", "simulation": "simulation", "sports": "sports",
    "racing": "racing", "puzzle": "puzzle", "horror": "horror",
    "shooter": "shooter", "platformer": "platformer", "fighting": "fighting",
    "stealth": "stealth", "survival": "survival", "indie": "indie",
    "casual": "casual", "mmo": "mmo", "moba": "moba",
    "battle royale": "battle_royale", "sandbox": "sandbox",
    "open world": "open_world", "story rich": "story_rich",
    "visual novel": "visual_novel", "tower defense": "tower_defense",
    "turn-based": "turn_based", "turn based": "turn_based",
    "real-time strategy": "real_time_strategy",
    "real time strategy": "real_time_strategy",
    "first-person": "first_person", "third-person": "third_person",
    "top-down": "top_down", "top down": "top_down",
    "metroidvania": "metroidvania", "roguelike": "roguelike",
    "soulslike": "soulslike", "hack and slash": "hack_and_slash",
    "management": "management", "city builder": "city_builder",
    "exploration": "exploration", "atmospheric": "atmospheric",
    "anime": "anime", "early access": "early_access",
    "free to play": "free_to_play",
    # Spanish (Steam delivers in ES on Spanish OS)
    "acción": "action", "accion": "action",
    "aventura": "adventure", "estrategia": "strategy",
    "simulación": "simulation", "simulacion": "simulation",
    "deportes": "sports", "carreras": "racing",
    "puzle": "puzzle", "terror": "horror",
    "plataformas": "platformer", "lucha": "fighting",
    "sigilo": "stealth", "supervivencia": "survival",
    "mundo abierto": "open_world", "novela visual": "visual_novel",
    "por turnos": "turn_based", "acceso anticipado": "early_access",
    "gratis": "free_to_play",
}


def translate_genre(genre_str: str) -> str:
    """Translate a single genre from Steam to the current i18n locale."""
    if not genre_str:
        return genre_str
    key = _GENRE_NORMALIZE.get(genre_str.lower().strip())
    if key:
        translated = i18n.t(f"genres.{key}")
        if translated and not translated.startswith("genres."):
            return translated
    return genre_str


def translate_genres(genres_str: str, sep: str = ", ") -> str:
    """Translate a comma-separated genres string from Steam."""
    if not genres_str:
        return genres_str
    parts = [translate_genre(g.strip()) for g in genres_str.split(",")]
    return sep.join(p for p in parts if p)


# ── helpers ──────────────────────────────────────────────────────────────────

def _hours(h: float) -> str:
    return i18n.t("library.hours", h=f"{h:,.0f}" if h >= 10 else f"{h:.1f}")


def _stat_grid(parent: QWidget) -> QGridLayout:
    g = QGridLayout(parent)
    g.setContentsMargins(0, 0, 0, 0)
    g.setSpacing(SP["md"])
    for c in range(4):
        g.setColumnStretch(c, 1)
    return g


def _set(tile: StatCard, value, fmt=None) -> None:
    """StatCard.set_value, but a zero renders immediately (0 -> 0 never animates)."""
    if isinstance(value, (int, float)) and value == 0:
        tile.set_value(fmt(0) if fmt else "0", animate=False)
    else:
        tile.set_value(value, fmt=fmt)


def _skeleton_tile() -> Card:
    c = Card(padding=SP["lg"], spacing=SP["sm"])
    c.body.addWidget(Skeleton(90, 10))
    c.body.addWidget(Skeleton(70, 26))
    c.body.addWidget(Skeleton(120, 10))
    return c


def _skeleton_row() -> Card:
    c = Card(padding=SP["md"], spacing=0)
    row = hbox(spacing=SP["md"])
    row.addWidget(Skeleton(22, 18))
    row.addWidget(Skeleton(180, 12))
    row.addStretch()
    row.addWidget(Skeleton(60, 12))
    c.body.addLayout(row)
    return c


# ── view ─────────────────────────────────────────────────────────────────────

class LibraryView(QWidget):
    """Steam library stats + curator stats + play status of purchased games."""

    def __init__(self, parent=None, notify: Optional[Callable] = None,
                 on_data_changed: Optional[Callable] = None, **_):
        super().__init__(parent)
        self._notify_dep = notify
        self._stats: Optional[dict] = None
        self._error: Optional[str] = None
        self._loading = False
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["xl"]), SP["lg"])
        self._refresh_btn = Button("", icon="refresh", on_click=self._force_refresh)
        self._header = SectionHeader("", "", actions=[self._refresh_btn])
        root.addWidget(self._header)

        content = QWidget()
        lay = vbox(content, (0, 0, SP["sm"], 0), SP["sm"])

        self._steam_head = SubHeader("")
        lay.addWidget(self._steam_head)
        self._steam_box = QWidget()
        self._steam_lay = vbox(self._steam_box, spacing=SP["md"])
        lay.addWidget(self._steam_box)

        lay.addSpacing(SP["md"])
        self._curator_head = SubHeader("")
        lay.addWidget(self._curator_head)
        self._curator_box = QWidget()
        self._curator_lay = vbox(self._curator_box, spacing=SP["md"])
        lay.addWidget(self._curator_box)

        lay.addSpacing(SP["md"])
        self._status_head = SubHeader("")
        lay.addWidget(self._status_head)
        self._status_desc = label("", "muted")
        lay.addWidget(self._status_desc)
        self._status_box = QWidget()
        self._status_lay = vbox(self._status_box, spacing=SP["md"])
        lay.addWidget(self._status_box)

        lay.addStretch()
        root.addWidget(scroll_area(content), 1)
        self.retranslate()

    # ── shell contract ───────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> None:
        """Re-render curator data now and (re)fetch the Steam stats."""
        if force:
            from services.library_api import invalidate_cache
            invalidate_cache()
            self._stats = None
        self._render_curator()
        self._render_status()
        self._fetch_steam()

    def retranslate(self) -> None:
        t = i18n.t
        self._header.title.setText(t("nav.library"))
        self._header.subtitle.setText(t("library.subtitle"))
        self._header.subtitle.setVisible(True)
        self._refresh_btn.setText(t("library.refresh"))
        self._steam_head.title.setText(t("library.section_steam"))
        self._curator_head.title.setText(t("library.section_curator"))
        self._status_head.title.setText(t("library.section_status"))
        self._status_desc.setText(t("library.status_desc"))
        if self._stats is not None or self._error is not None or not self._loading:
            self._render_steam()
        self._render_curator()
        self._render_status()

    # ── Steam section ────────────────────────────────────────────────────────

    def _force_refresh(self) -> None:
        self.refresh(force=True)

    def _fetch_steam(self) -> None:
        if self._loading:
            return
        from services.library_api import get_library_stats
        self._loading = True
        self._error = None
        self._refresh_btn.set_loading(True)
        if self._stats is None:
            self._render_steam()          # skeletons

        def on_done(result):
            self._loading = False
            self._refresh_btn.set_loading(False)
            if isinstance(result, Exception):
                self._stats = None
                self._error = str(result) or type(result).__name__
            else:
                self._stats = result or None
                self._error = None
            self._render_steam()

        run_async(self, get_library_stats, on_done=on_done)

    def _render_steam(self) -> None:
        clear_layout(self._steam_lay)
        if self._stats is not None:
            self._render_steam_stats(self._stats)
        elif self._loading:
            self._render_steam_skeleton()
        else:
            self._render_steam_error()

    def _render_steam_skeleton(self) -> None:
        grid_w = QWidget()
        grid = _stat_grid(grid_w)
        for i in range(4):
            grid.addWidget(_skeleton_tile(), 0, i)
        self._steam_lay.addWidget(grid_w)
        cols = hbox(spacing=SP["lg"])
        for _ in range(2):
            col = vbox(spacing=SP["sm"])
            col.addWidget(Skeleton(110, 10))
            for _ in range(4):
                col.addWidget(_skeleton_row())
            col.addStretch()
            cols.addLayout(col, 1)
        self._steam_lay.addLayout(cols)

    def _render_steam_error(self) -> None:
        t = i18n.t
        btn = Button(t("library.open_settings"), variant="primary", icon="settings",
                     on_click=self._open_settings)
        card = Card(padding=SP["sm"])
        card.body.addWidget(EmptyState("library", t("library.error_title"),
                                       self._error or t("library.connect_desc"), action=btn))
        self._steam_lay.addWidget(card)

    def _open_settings(self) -> None:
        win = self.window()
        if hasattr(win, "show_view"):
            win.show_view("settings")

    def _render_steam_stats(self, s: dict) -> None:
        t = i18n.t
        total = int(s.get("total_games") or 0)
        never = int(s.get("never_played_count") or 0)
        played = int(s.get("played_count") or 0)
        recent = s.get("recently_played") or []
        hours_2w = sum(float(g.get("hours_2w") or 0) for g in recent)
        never_pct = round(never / total * 100) if total else 0

        grid_w = QWidget()
        grid = _stat_grid(grid_w)
        tiles = [
            StatCard(t("library.games_owned"), icon="gamepad-2", tone="accent",
                     caption=t("library.played_caption", n=f"{played:,}")),
            StatCard(t("library.total_hours"), icon="clock", tone="violet",
                     caption=t("library.avg_caption", h=f"{float(s.get('avg_playtime_hours') or 0):,.1f}")),
            StatCard(t("library.played_2w"), icon="play", tone="green",
                     caption=t("library.played_2w_caption", h=f"{hours_2w:,.1f}")),
            StatCard(t("library.never_played"), icon="moon", tone=C["text_dim"],
                     caption=t("library.never_pct", pct=never_pct)),
        ]
        _set(tiles[0], total)
        _set(tiles[1], float(s.get("total_playtime_hours") or 0), fmt=_hours)
        _set(tiles[2], len(recent))
        _set(tiles[3], never)
        for i, tile in enumerate(tiles):
            grid.addWidget(tile, 0, i)
        self._steam_lay.addWidget(grid_w)

        cols = hbox(spacing=SP["lg"])
        # most played
        left = vbox(spacing=SP["sm"])
        left.addWidget(label(t("library.top_played"), "eyebrow"))
        top = (s.get("top_played") or [])[:_TOP_N]
        max_h = max((float(g.get("hours") or 0) for g in top), default=0) or 1
        for i, g in enumerate(top, start=1):
            trailing = QWidget()
            tr = hbox(trailing, spacing=SP["sm"])
            bar = QProgressBar()
            bar.setFixedWidth(_BAR_WIDTH)
            bar.setTextVisible(False)
            bar.setRange(0, 1000)
            bar.setValue(int(float(g.get("hours") or 0) / max_h * 1000))
            tr.addWidget(bar)
            hl = label(_hours(float(g.get("hours") or 0)), "mono", color=C["text_2"])
            hl.setFixedWidth(64)
            hl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tr.addWidget(hl)
            rank = Pill(f"{i:02d}", "gold" if i == 1 else "neutral")
            left.addWidget(ListRow(g.get("name", "?"), leading=rank, trailing=trailing, clickable=False))
        if not top:
            left.addWidget(label(t("library.recent_none"), "muted"))
        left.addStretch()
        cols.addLayout(left, 1)

        # recently played
        right = vbox(spacing=SP["sm"])
        right.addWidget(label(t("library.recently_played"), "eyebrow"))
        for g in recent:
            hl = label(_hours(float(g.get("hours_2w") or 0)), "mono", color=C["accent"])
            right.addWidget(ListRow(g.get("name", "?"),
                                    t("library.hours_total", h=f"{float(g.get('hours_total') or 0):,.0f}"),
                                    trailing=hl, clickable=False))
        if not recent:
            right.addWidget(label(t("library.recent_none"), "muted"))
        right.addStretch()
        cols.addLayout(right, 1)
        self._steam_lay.addLayout(cols)

    # ── curator section ──────────────────────────────────────────────────────

    def _render_curator(self) -> None:
        t = i18n.t
        clear_layout(self._curator_lay)
        games = repo.get_all()
        bought = purchases.get_all()
        wishlist = [g for g in games if normalize_status(g.status) == STATUS_WISHLIST]
        archived = [g for g in games if normalize_status(g.status) == STATUS_ARCHIVED]

        grid_w = QWidget()
        grid = _stat_grid(grid_w)
        tiles = [
            (StatCard(t("library.on_wishlist"), icon="heart", tone="accent"), len(wishlist)),
            (StatCard(t("library.archived"), icon="bookmark", tone=C["text_dim"]), len(archived)),
            (StatCard(t("library.total_tracked"), icon="layers", tone="violet"), len(games)),
            (StatCard(t("library.games_bought"), icon="shopping-cart", tone="green"), len(bought)),
        ]
        for i, (tile, value) in enumerate(tiles):
            _set(tile, value)
            grid.addWidget(tile, 0, i)
        self._curator_lay.addWidget(grid_w)

        if bought:
            currency = bought[0].currency
            spent = sum(p.price_paid for p in bought)
            saved = sum(p.saved for p in bought)
            base = sum(p.base_price for p in bought)
            avg_disc = saved / base * 100 if base else 0
            grid2_w = QWidget()
            grid2 = _stat_grid(grid2_w)
            money_tiles = [
                (StatCard(t("library.total_spent"), icon="wallet", tone="gold",
                          caption=t("library.spent_caption", n=len(bought))), spent),
                (StatCard(t("library.total_saved"), icon="piggy-bank", tone="green",
                          caption=t("library.saved_caption")), saved),
                (StatCard(t("library.avg_discount"), icon="percent", tone="pink", caption=" "), None),
                (StatCard(t("library.avg_per_game_spent"), icon="coins", tone="cyan", caption=" "),
                 spent / len(bought)),
            ]
            for i, (tile, value) in enumerate(money_tiles):
                if value is None:
                    tile.set_value(pct(avg_disc), animate=False)
                else:
                    _set(tile, value, fmt=lambda v, c=currency: money(v, c))
                grid2.addWidget(tile, 0, i)
            self._curator_lay.addWidget(grid2_w)

        priced = [g for g in wishlist if g.price and g.price.current > 0]
        if priced:
            total = sum(g.price.current for g in priced)
            card = Card(padding=SP["lg"], spacing=0)
            row = hbox(spacing=SP["md"])
            col = vbox(spacing=2)
            col.addWidget(label(t("library.wishlist_value"), "body"))
            col.addWidget(label(t("library.wishlist_value_caption", n=len(priced)), "muted"))
            row.addLayout(col, 1)
            row.addWidget(label(money(total, priced[0].price.currency), "value", color=C["accent"]))
            card.body.addLayout(row)
            self._curator_lay.addWidget(card)

    # ── play status section ──────────────────────────────────────────────────

    def _render_status(self) -> None:
        t = i18n.t
        clear_layout(self._status_lay)
        owned = [g for g in repo.get_all() if normalize_status(g.status) == STATUS_PURCHASED]
        self._status_desc.setVisible(bool(owned))
        if not owned:
            self._status_lay.addWidget(label(t("library.mark_to_see"), "muted"))
            return

        counts = {k: 0 for k in PLAY_STATUSES if k}
        for g in owned:
            if g.play_status in counts:
                counts[g.play_status] += 1
        grid_w = QWidget()
        grid = _stat_grid(grid_w)
        for i, (key, (icon, tone)) in enumerate(PLAY_STATUS_STYLE.items()):
            tile = StatCard(t(f"play_status.{key}"), icon=icon, tone=tone)
            _set(tile, counts[key])
            grid.addWidget(tile, 0, i)
        self._status_lay.addWidget(grid_w)

        for g in sorted(owned, key=lambda x: x.name.lower()):
            self._status_lay.addWidget(self._status_row(g))

    def _status_row(self, game: Game) -> ListRow:
        t = i18n.t
        combo = QComboBox()
        combo.setMinimumHeight(30)
        combo.setMinimumWidth(150)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for key in PLAY_STATUSES:
            combo.addItem(t(f"play_status.{key}") if key else t("library.play_status_none"), key)
        idx = PLAY_STATUSES.index(game.play_status) if game.play_status in PLAY_STATUSES else 0
        combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(lambda _i, g=game, c=combo: self._set_play_status(g, c.currentData()))
        bits = [translate_genres(game.genre) if game.genre else "", str(game.release_year or "")]
        subtitle = " · ".join(b for b in bits if b)
        return ListRow(game.name, subtitle, leading=PriorityBadge(game.priority), trailing=combo,
                       clickable=False)

    def _set_play_status(self, game: Game, key: str) -> None:
        key = key or ""
        if key == (game.play_status or ""):
            return
        game.play_status = key
        repo.update(game)
        self._render_status()
