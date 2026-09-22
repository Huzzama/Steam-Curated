"""
Deals — the current / next Steam sale as a hero banner with a live countdown,
the other upcoming sale events, and the wishlist games that are on sale now.

    DealsView(parent, on_game_click=open_detail)
    view.refresh(force=False)     re-read games + cached sale dates and re-render
                                  (force=True also drops the cached banner pixmaps;
                                  the shell calls it when banners finish downloading)
    view.retranslate()            update visible strings in place

Everything renders synchronously from the repository and the sale-image cache
(services.sale_images) — no polling. The only timer is the 1 s countdown clock,
which touches one label and runs only while the view is visible.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QWidget

import i18n
import data.repository as repo
from config import BUNDLE_DIR, STEAM_SALE_EVENTS
from data.models import Game
from data.status import STATUS_PURCHASED, normalize_status
from services import sale_images
from ui import icons
from ui.animations import clear_layout
from ui.components import (Card, ChipGroup, ElidedLabel, EmptyState, FlowLayout, Pill, SectionHeader,
                           SubHeader, hbox, label, scroll_area, vbox)
from ui.event_time import event_state, hero_event, parse_gmt_offset, visible_events
from ui.format import day
from ui.game_card import GameCard
from ui.settings_loader import get_settings
from ui.theme import C, R, SP

HERO_H = 208                 # hero banner height
EVENT_CARD_W = 292           # upcoming-event card width (FlowLayout)
FILTERS = ("all", "sa", "half", "low")
_LOW_TOLERANCE = 1.05        # "at all-time low" = within 5 % of the low (same rule as GameCard)
_YEAR_SUFFIX = re.compile(r"_(\d{4})$")
_BANNER_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_banner_cache: dict[str, QPixmap] = {}


# ── helpers ───────────────────────────────────────────────────────────────────

def _on_sale(g: Game) -> bool:
    return g.price is not None and g.price.is_on_sale and g.price.discount_pct > 0


def _at_low(g: Game) -> bool:
    p, h = g.price, g.price_history
    return p is not None and h is not None and h.all_time_low > 0 and p.current <= h.all_time_low * _LOW_TOLERANCE


def _is_purchased(g: Game) -> bool:
    return normalize_status(g.status) == STATUS_PURCHASED


def event_name(event: dict) -> str:
    """Server-provided name, else the i18n sale_events.* entry (with or without
    the year suffix), else a title-cased key."""
    if event.get("name"):
        return str(event["name"])
    key = str(event.get("key", ""))
    t = i18n.t(f"sale_events.{key}")
    if t != f"sale_events.{key}":
        return t
    m = _YEAR_SUFFIX.search(key)
    if m:
        base = key[:m.start()]
        t = i18n.t(f"sale_events.{base}")
        if t != f"sale_events.{base}":
            return f"{t} {m.group(1)}"
    return key.replace("_", " ").title()


def date_range(event: dict, compact: bool = False) -> str:
    """'27 Oct 2026 – 31 Oct 2026'; compact drops the year from the start when both share it."""
    start, end = event.get("start"), event.get("end")
    if compact and start and end and str(start)[:4] == str(end)[:4]:
        return f"{day(start, '{d} {mon}')} – {day(end)}"
    return f"{day(start)} – {day(end)}"


def banner_path(event: dict) -> Optional[Path]:
    """Downloaded banner for the event's server_img key, else the bundled one."""
    key = str(event.get("server_img") or "")
    if key:
        p = sale_images.get_local_path(key)
        if p is not None and Path(p).exists():
            return Path(p)
    folder = Path(BUNDLE_DIR) / "assets" / "sale_banners"
    for stem in (event.get("key"), key):
        if not stem:
            continue
        for ext in _BANNER_EXTS:
            f = folder / f"{stem}{ext}"
            if f.exists():
                return f
    return None


def _banner_pixmap(event: dict) -> Optional[QPixmap]:
    path = banner_path(event)
    if path is None:
        return None
    key = str(path)
    pm = _banner_cache.get(key)
    if pm is None:
        pm = QPixmap(key)
        _banner_cache[key] = pm
    return None if pm.isNull() else pm


def countdown_text(seconds: int) -> str:
    """'12d 04h 33m' while days remain, '04h 33m 12s' on the last day."""
    if seconds <= 0:
        return i18n.t("deals.now")
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}d {h:02d}h {m:02d}m" if d > 0 else f"{h:02d}h {m:02d}m {s:02d}s"


def _icon_chip(name: str, color: str, size: int = 18, box: int = 36) -> QFrame:
    """Small inset square with a tinted icon (used as a card leading element)."""
    chip = QFrame()
    chip.setProperty("surface", "inset")
    chip.setFixedSize(box, box)
    lay = hbox(chip, (0, 0, 0, 0), 0)
    ic = QLabel()
    ic.setPixmap(icons.pixmap(name, color, size))
    ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(ic)
    return chip


# ── hero banner ───────────────────────────────────────────────────────────────

class HeroBanner(QWidget):
    """
    Rounded banner surface: the sale image cover-cropped (or a two-tone fill
    from the event colours when there is none) under a dark scrim that fades
    into the page background, so ordinary labels stay legible on top.
    This is the one place in the views that paints a gradient.
    """

    def __init__(self, parent=None, radius: int = R["lg"]):
        super().__init__(parent)
        self._radius = radius
        self._pix: Optional[QPixmap] = None
        self._scaled: Optional[QPixmap] = None
        self._top = QColor(C["surface_3"])
        self._bot = QColor(C["surface"])
        self.setMinimumHeight(HERO_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_background(self, pixmap: Optional[QPixmap], color_top: Optional[str] = None,
                       color_bot: Optional[str] = None) -> None:
        self._pix = pixmap if pixmap is not None and not pixmap.isNull() else None
        self._scaled = None
        top, bot = QColor(color_top or ""), QColor(color_bot or "")
        self._top = top if top.isValid() else QColor(C["surface_3"])
        self._bot = bot if bot.isValid() else QColor(C["surface"])
        self.update()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._scaled = None

    def _scaled_pixmap(self, w: int, h: int) -> Optional[QPixmap]:
        if self._pix is None:
            return None
        if self._scaled is None or self._scaled.width() < w or self._scaled.height() < h:
            self._scaled = self._pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                            Qt.TransformationMode.SmoothTransformation)
        return self._scaled

    def paintEvent(self, e) -> None:
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), self._radius, self._radius)
        p.setClipPath(path)

        scaled = self._scaled_pixmap(w, h)
        if scaled is not None:
            p.drawPixmap((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
        else:
            fill = QLinearGradient(0, 0, w, h)
            fill.setColorAt(0.0, self._top)
            fill.setColorAt(1.0, self._bot)
            p.fillRect(self.rect(), fill)

        bg = QColor(C["bg"])
        vertical = QLinearGradient(0, 0, 0, h)
        c0, c1 = QColor(bg), QColor(bg)
        c0.setAlpha(48)
        c1.setAlpha(228)
        vertical.setColorAt(0.0, c0)
        vertical.setColorAt(1.0, c1)
        p.fillRect(self.rect(), vertical)

        horizontal = QLinearGradient(0, 0, w, 0)
        h0, h1 = QColor(bg), QColor(bg)
        h0.setAlpha(150)
        h1.setAlpha(0)
        horizontal.setColorAt(0.0, h0)
        horizontal.setColorAt(0.62, h1)
        p.fillRect(self.rect(), horizontal)

        p.setClipping(False)
        p.setPen(QPen(QColor(C["border_strong"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()


# ── view ──────────────────────────────────────────────────────────────────────

class DealsView(QWidget):
    """Hero sale banner + upcoming sale events + wishlist games on sale."""

    def __init__(self, parent=None, on_game_click: Optional[Callable[[Game], None]] = None, **deps):
        super().__init__(parent)
        self._on_game_click = on_game_click
        self._events: list[dict] = []
        self._hero: Optional[dict] = None
        self._hero_state = "upcoming"
        self._target: Optional[datetime] = None
        self._tz = parse_gmt_offset("GMT-6")
        self._games: list[Game] = []
        self._filter = "all"
        self._loaded = False
        self._rendering = False

        self._timer = QTimer(self)              # countdown clock — the only timer here
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["xl"]), SP["lg"])
        self._header = SectionHeader("", "")
        root.addWidget(self._header)

        content = QWidget()
        self._content = vbox(content, (0, 0, SP["sm"], 0), SP["md"])

        # hero
        self._banner = HeroBanner()
        hl = hbox(self._banner, (SP["xl"], SP["lg"], SP["xl"], SP["lg"]), SP["lg"])
        left = vbox(spacing=SP["xs"])
        top = hbox(spacing=SP["sm"])
        self._eyebrow = label("", "eyebrow")
        top.addWidget(self._eyebrow)
        self._state_pill = Pill("", "neutral")
        top.addWidget(self._state_pill)
        top.addStretch()
        left.addLayout(top)
        self._name = label("", "title", family="display", size="3xl")
        left.addWidget(self._name)
        dates = hbox(spacing=SP["xs"])
        cal = QLabel()
        cal.setPixmap(icons.pixmap("calendar", C["text_dim"], 13))
        dates.addWidget(cal)
        self._dates = label("", "dim")
        dates.addWidget(self._dates)
        dates.addStretch()
        left.addLayout(dates)
        left.addStretch()
        self._count_label = label("", "eyebrow")
        left.addWidget(self._count_label)
        self._countdown = label("", "value", color=C["text"])
        left.addWidget(self._countdown)
        hl.addLayout(left, 1)

        right = vbox(spacing=SP["sm"])
        self._hero_icon = QLabel()
        self._hero_icon.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        right.addWidget(self._hero_icon)
        right.addStretch()
        self._sale_pill = Pill("", "green")
        right.addWidget(self._sale_pill, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        hl.addLayout(right)
        self._content.addWidget(self._banner)

        self._no_events = EmptyState("calendar", "", "")
        self._no_events.setMinimumHeight(HERO_H)
        self._no_events.hide()
        self._content.addWidget(self._no_events)

        # upcoming events
        self._events_count = label("", "muted")
        self._events_header = SubHeader("", trailing=self._events_count)
        self._content.addWidget(self._events_header)
        self._events_host = QWidget()
        self._events_flow = FlowLayout(self._events_host, SP["md"], SP["md"])
        self._content.addWidget(self._events_host)

        # games on sale
        self._currency_note = label("", "muted")
        self._games_header = SubHeader("", trailing=self._currency_note)
        self._content.addWidget(self._games_header)
        self._chips = ChipGroup([(k, "") for k in FILTERS], current="all")
        self._chips.changed.connect(self._on_filter)
        self._content.addWidget(self._chips)
        self._grid_host = QWidget()
        self._grid = FlowLayout(self._grid_host, SP["md"], SP["md"])
        self._content.addWidget(self._grid_host)
        self._empty = EmptyState("tag", "", "")
        self._empty.setMinimumHeight(220)
        self._empty.hide()
        self._content.addWidget(self._empty)
        self._content.addStretch()

        root.addWidget(scroll_area(content), 1)
        self.retranslate()

    # ── shell contract ───────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> None:
        """Re-read the wishlist and the cached sale dates; force drops the banner cache."""
        if force:
            _banner_cache.clear()
        settings = get_settings()
        self._tz = parse_gmt_offset(settings.get("timezone", "GMT-6"))
        self._events = sale_images.get_sale_events() or list(STEAM_SALE_EVENTS)
        self._games = [g for g in repo.get_on_sale() if _on_sale(g) and not _is_purchased(g)]
        self._loaded = True
        self._render()

    def retranslate(self) -> None:
        t = i18n.t
        self._header.title.setText(t("deals.title"))
        self._events_header.title.setText(t("deals.upcoming"))
        self._games_header.title.setText(t("deals.on_sale"))
        self._chips.set_label("all", t("filters.all"))
        self._chips.set_label("sa", t("filters.priority_sa"))
        self._chips.set_label("half", t("deals.filter_half"))
        self._chips.set_label("low", t("stats.min_value"))
        self._no_events.title.setText(t("deals.no_events_title"))
        self._no_events.subtitle.setText(t("deals.no_events_subtitle"))
        self._no_events.subtitle.setVisible(True)
        if self._loaded:
            self._render()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self._target is not None:
            self._tick()
            self._timer.start()

    def hideEvent(self, e) -> None:
        self._timer.stop()
        super().hideEvent(e)

    # ── render ───────────────────────────────────────────────────────────────

    def _render(self) -> None:
        self._rendering = True
        try:
            self._render_hero()
            self._render_events()
            self._render_games()
            self._update_subtitle()
        finally:
            self._rendering = False

    def _tz_name(self) -> str:
        return get_settings().get("timezone", "GMT-6")

    def _render_hero(self) -> None:
        tz = self._tz_name()
        hero = hero_event(self._events, tz)
        self._hero = hero
        self._timer.stop()
        if hero is None:
            self._target = None
            self._banner.hide()
            self._no_events.show()
            return
        self._no_events.hide()
        self._banner.show()

        state, target = event_state(hero, tz)
        self._hero_state, self._target = state, target
        live = state == "active"
        t = i18n.t
        self._eyebrow.setText(t("deals.eyebrow_live" if live else "deals.eyebrow_next").upper())
        if live:
            self._state_pill.setText(t("deals.live").upper())
            self._state_pill.set_tone("green")
        elif hero.get("confirmed"):
            self._state_pill.setText(t("deals.confirmed").upper())
            self._state_pill.set_tone("accent")
        else:
            self._state_pill.setText(t("deals.estimated").upper())
            self._state_pill.set_tone("neutral")
        self._name.setText(event_name(hero))
        self._dates.setText(date_range(hero))
        self._count_label.setText(t("deals.ends_in_short" if live else "deals.starts_in_short").upper())
        self._hero_icon.setPixmap(icons.pixmap(icons.sale_icon(hero.get("key", "")), C["text"], 44, 1.25))
        n = len(self._games)
        self._sale_pill.setVisible(n > 0)
        self._sale_pill.setText(t("deals.wishlist_on_sale_one" if n == 1 else "deals.wishlist_on_sale_other", n=n))
        self._banner.set_background(_banner_pixmap(hero), hero.get("color_top"), hero.get("color_bot"))
        self._tick()
        if self.isVisible():
            self._timer.start()

    def _tick(self) -> None:
        """Countdown clock (1 s). When the target passes, re-render once so the
        hero flips from 'next' to 'live' (or to the following event)."""
        if self._target is None:
            return
        remaining = (self._target - datetime.now(self._tz)).total_seconds()
        self._countdown.setText(countdown_text(int(remaining)))
        if remaining <= 0:
            self._timer.stop()
            self._target = None
            if not self._rendering:
                self._render()

    def _render_events(self) -> None:
        clear_layout(self._events_flow)
        tz = self._tz_name()
        hero_key = self._hero.get("key") if self._hero else None
        others = [e for e in visible_events(self._events, tz) if e is not self._hero and e.get("key") != hero_key]
        self._events_header.setVisible(bool(others))
        self._events_host.setVisible(bool(others))
        if not others:
            return
        self._events_count.setText(i18n.t("deals.events_one" if len(others) == 1 else "deals.events_other",
                                          n=len(others)))
        now = datetime.now(self._tz)
        for ev in others:
            self._events_flow.addWidget(self._event_card(ev, tz, now))

    def _event_card(self, ev: dict, tz: str, now: datetime) -> Card:
        t = i18n.t
        state, target = event_state(ev, tz)
        live = state == "active"
        days = max(0, (target - now).days)
        card = Card(padding=SP["md"], spacing=SP["sm"])
        card.setFixedWidth(EVENT_CARD_W)
        row = hbox(spacing=SP["md"])
        row.addWidget(_icon_chip(icons.sale_icon(ev.get("key", "")), C["green"] if live else C["accent"]),
                      0, Qt.AlignmentFlag.AlignTop)
        col = vbox(spacing=2)
        col.addWidget(ElidedLabel(event_name(ev), "body"))
        col.addWidget(ElidedLabel(date_range(ev, compact=True), "muted"))
        row.addLayout(col, 1)
        card.body.addLayout(row)
        foot = hbox(spacing=SP["sm"])
        if live:
            pill = Pill(t("deals.live").upper(), "green")
        elif ev.get("confirmed"):
            pill = Pill(t("deals.confirmed").upper(), "accent")
        else:
            pill = Pill(t("deals.estimated").upper(), "neutral")
        foot.addWidget(pill)
        foot.addStretch()
        if live:
            when = t("deals.days_left", n=days) if days else t("deals.ends_today")
        else:
            when = t("deals.starts_in", n=days) if days else t("deals.starts_today")
        foot.addWidget(label(when, "mono", size="xs", color=C["green"] if live else C["text_dim"]))
        card.body.addLayout(foot)
        return card

    def _on_filter(self, key: str) -> None:
        self._filter = key
        self._render_games()

    def _filtered(self) -> list[Game]:
        games = self._games
        if self._filter == "sa":
            games = [g for g in games if g.priority in ("S", "A")]
        elif self._filter == "half":
            games = [g for g in games if g.price.discount_pct >= 50]
        elif self._filter == "low":
            games = [g for g in games if _at_low(g)]
        return sorted(games, key=lambda g: (-g.price.discount_pct, (g.name or "").casefold()))

    def _render_games(self) -> None:
        t = i18n.t
        clear_layout(self._grid)
        has_any = bool(self._games)
        shown = self._filtered() if has_any else []
        self._chips.setVisible(has_any)
        currency = next((g.price.currency for g in self._games if g.price and g.price.currency), "")
        self._currency_note.setText(t("deals.currency_note", currency=currency) if currency else "")
        self._currency_note.setVisible(bool(currency))
        if not shown:
            if has_any:
                self._empty.title.setText(t("deals.filter_empty_title"))
                self._empty.subtitle.setText(t("deals.filter_empty_subtitle"))
            else:
                self._empty.title.setText(t("deals.no_deals"))
                self._empty.subtitle.setText(t("deals.empty_hint"))
            self._empty.subtitle.setVisible(True)
            self._grid_host.hide()
            self._empty.show()
            return
        self._empty.hide()
        self._grid_host.show()
        self._grid_host.setUpdatesEnabled(False)
        try:
            for g in shown:
                self._grid.addWidget(GameCard(g, on_click=self._on_game_click))
        finally:
            self._grid_host.setUpdatesEnabled(True)

    def _update_subtitle(self) -> None:
        t = i18n.t
        n = len(self._games)
        bits = [t("deals.subtitle_sale_one" if n == 1 else "deals.subtitle_sale_other", n=n) if n
                else t("deals.subtitle_none")]
        if self._hero is not None and self._target is not None:
            if self._hero_state == "active":
                bits.append(t("deals.subtitle_live", name=event_name(self._hero)))
            else:
                days = max(0, (self._target - datetime.now(self._tz)).days)
                bits.append(t("deals.subtitle_next", n=days) if days else t("deals.subtitle_next_today"))
        self._header.subtitle.setText(" · ".join(bits))
        self._header.subtitle.setVisible(True)
