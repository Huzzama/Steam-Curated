"""
Non-Steam festivals — publisher sales, developer events and festivals that
are not part of Steam's own seasonal sales, tracked through SteamDB.

    NonSteamView(parent, events=None)     # NonSteamFestivalsView is an alias
    view.refresh(force=False)             re-read the event list and re-render
    view.retranslate()                    update visible strings in place
    view.set_events(events)               swap in a live event feed

Event dicts (any source) follow this shape:
    {"key": str, "url": str, "icon": str,                  # icon: ui.icons name
     "name": str | "title_key": "non_steam.x",              # one of the two
     "subtitle": str | "desc_key": "non_steam.y",           # optional
     "start": "YYYY-MM-DD", "end": "YYYY-MM-DD",            # optional → state via ui.event_time
     "state": "upcoming" | "live" | "past"}                 # used when there are no dates

There is no non-Steam event feed yet (the previous view had none either), so
the default source is a static catalogue of SteamDB pages bucketed into the
three states. `set_events` is the hook for a real feed later.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QLabel, QWidget

import i18n
from ui import icons
from ui.animations import clear_layout
from ui.components import (Button, Card, EmptyState, ListRow, Pill, SectionHeader, Segmented, SubHeader,
                           hbox, label, scroll_area, vbox)
from ui.event_time import event_state
from ui.format import day
from ui.settings_loader import get_settings
from ui.theme import C, SP

STEAMDB_URL = "https://steamdb.info"
LIVE_SALES_URL = f"{STEAMDB_URL}/sales/history/all/?live"
STATES = ("upcoming", "live", "past")
_STATE_TONE = {"upcoming": "accent", "live": "green", "past": "neutral"}
_STATE_ICON = {"upcoming": "calendar", "live": "radio", "past": "clock-fading"}


def default_events() -> list[dict]:
    """The SteamDB catalogue the old view linked to, bucketed by timeframe."""
    return [
        {"key": "live", "state": "live", "icon": "radio", "url": LIVE_SALES_URL,
         "title_key": "non_steam.link_live", "desc_key": "non_steam.desc_live"},
        {"key": "charts", "state": "live", "icon": "chart-line", "url": f"{STEAMDB_URL}/charts/",
         "title_key": "non_steam.link_charts", "desc_key": "non_steam.desc_charts"},
        {"key": "calendar", "state": "upcoming", "icon": "calendar", "url": f"{STEAMDB_URL}/calendar/",
         "title_key": "non_steam.link_calendar", "desc_key": "non_steam.desc_calendar"},
        {"key": "upcoming", "state": "upcoming", "icon": "hourglass", "url": f"{STEAMDB_URL}/upcoming/",
         "title_key": "non_steam.link_upcoming", "desc_key": "non_steam.desc_upcoming"},
        {"key": "all_sales", "state": "past", "icon": "clock-fading", "url": f"{STEAMDB_URL}/sales/history/",
         "title_key": "non_steam.link_all_sales", "desc_key": "non_steam.desc_all_sales"},
        {"key": "calculator", "state": "past", "icon": "calculator", "url": f"{STEAMDB_URL}/calculator/",
         "title_key": "non_steam.link_calculator", "desc_key": "non_steam.desc_calculator"},
    ]


def event_title(ev: dict) -> str:
    if ev.get("name"):
        return str(ev["name"])
    return i18n.t(ev.get("title_key", "")) if ev.get("title_key") else str(ev.get("key", ""))


def event_subtitle(ev: dict) -> str:
    if ev.get("start") or ev.get("end"):
        return f"{day(ev.get('start'))} – {day(ev.get('end'))}"
    if ev.get("subtitle"):
        return str(ev["subtitle"])
    if ev.get("desc_key"):
        return i18n.t(ev["desc_key"])
    return _host(ev.get("url", ""))


def state_of(ev: dict, tz: str) -> str:
    """upcoming · live · past — from the dates when present, else the static field."""
    if ev.get("start") and ev.get("end"):
        try:
            s = event_state(ev, tz)[0]
        except (ValueError, IndexError, TypeError):
            s = "past"
        return {"active": "live", "expired": "past"}.get(s, "upcoming")
    s = str(ev.get("state", "upcoming"))
    return s if s in STATES else "upcoming"


def _host(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


def open_url(url: str) -> None:
    if url:
        QDesktopServices.openUrl(QUrl(url))


def _icon_chip(name: str, color: str, size: int = 18, box: int = 38) -> QFrame:
    chip = QFrame()
    chip.setProperty("surface", "inset")
    chip.setFixedSize(box, box)
    lay = hbox(chip, (0, 0, 0, 0), 0)
    ic = QLabel()
    ic.setPixmap(icons.pixmap(name, color, size))
    ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(ic)
    return chip


class NonSteamView(QWidget):
    """SteamDB hero card + Upcoming · Live · Past list of events with links."""

    def __init__(self, parent=None, events: Optional[list[dict]] = None, **deps):
        super().__init__(parent)
        self._source: Optional[Callable[[], list[dict]]] = (lambda: list(events)) if events is not None else None
        self._events: list[dict] = []
        self._segment = "live"
        self._loaded = False
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["xl"]), SP["lg"])
        self._open_btn = Button("", icon="external", on_click=lambda: open_url(STEAMDB_URL))
        self._header = SectionHeader("", "", actions=[self._open_btn])
        root.addWidget(self._header)

        toolbar = hbox(spacing=SP["md"])
        self._seg = Segmented([(k, "") for k in STATES], current=self._segment)
        self._seg.changed.connect(self._on_segment)
        toolbar.addWidget(self._seg)
        toolbar.addStretch()
        self._count = label("", "muted")
        toolbar.addWidget(self._count)
        root.addLayout(toolbar)

        content = QWidget()
        self._content = vbox(content, (0, 0, SP["sm"], 0), SP["md"])

        # hero card (SteamDB live sales)
        hero = Card(padding=SP["xl"], spacing=SP["md"])
        row = hbox(spacing=SP["lg"])
        row.addWidget(_icon_chip("globe", C["accent"], 24, 52), 0, Qt.AlignmentFlag.AlignTop)
        col = vbox(spacing=SP["xs"])
        self._hero_eyebrow = label("", "eyebrow")
        col.addWidget(self._hero_eyebrow)
        self._hero_title = label("", "h2")
        col.addWidget(self._hero_title)
        self._hero_desc = label("", "dim", wrap=True)
        col.addWidget(self._hero_desc)
        col.addSpacing(SP["sm"])
        actions = hbox(spacing=SP["md"])
        self._hero_btn = Button("", variant="primary", icon="external", on_click=lambda: open_url(LIVE_SALES_URL))
        actions.addWidget(self._hero_btn)
        self._hero_url = label("", "muted", family="mono")
        actions.addWidget(self._hero_url)
        actions.addStretch()
        col.addLayout(actions)
        row.addLayout(col, 1)
        hero.body.addLayout(row)
        self._content.addWidget(hero)

        # list
        self._list_header = SubHeader("")
        self._content.addWidget(self._list_header)
        self._list_host = QWidget()
        self._list = vbox(self._list_host, spacing=SP["sm"])
        self._content.addWidget(self._list_host)
        self._empty = EmptyState("globe", "", "")
        self._empty.setMinimumHeight(220)
        self._empty.hide()
        self._content.addWidget(self._empty)
        self._content.addStretch()

        root.addWidget(scroll_area(content), 1)
        self.retranslate()

    # ── shell contract ───────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> None:
        """Re-read the event list (static catalogue unless set_events was used)."""
        self._events = self._source() if self._source else default_events()
        self._loaded = True
        self._render()

    def retranslate(self) -> None:
        t = i18n.t
        self._header.title.setText(t("non_steam.title"))
        self._header.subtitle.setText(t("non_steam.subtitle"))
        self._header.subtitle.setVisible(True)
        self._open_btn.setText(t("non_steam.open_steamdb"))
        for k in STATES:
            self._seg.set_label(k, t(f"non_steam.seg_{k}"))
        self._hero_eyebrow.setText(t("non_steam.badge").upper())
        self._hero_title.setText(t("non_steam.hero_title"))
        self._hero_desc.setText(t("non_steam.hero_desc").replace("\n", " "))
        self._hero_btn.setText(t("non_steam.hero_btn"))
        self._hero_url.setText(t("non_steam.hero_url"))
        self._empty.title.setText(t("non_steam.empty_title"))
        self._empty.subtitle.setText(t("non_steam.empty_subtitle"))
        self._empty.subtitle.setVisible(True)
        if self._loaded:
            self._render()

    def set_events(self, events: list[dict]) -> None:
        """Use a live feed instead of the static catalogue (re-renders)."""
        self._source = lambda: list(events)
        self.refresh()

    # ── render ───────────────────────────────────────────────────────────────

    def _on_segment(self, key: str) -> None:
        self._segment = key
        self._render()

    def _render(self) -> None:
        t = i18n.t
        tz = get_settings().get("timezone", "GMT-6")
        shown = [e for e in self._events if state_of(e, tz) == self._segment]
        self._list_header.title.setText(t(f"non_steam.list_{self._segment}"))
        self._count.setText(t("non_steam.count_one" if len(shown) == 1 else "non_steam.count_other", n=len(shown)))
        clear_layout(self._list)
        self._empty.setVisible(not shown)
        self._list_host.setVisible(bool(shown))
        self._list_header.setVisible(bool(shown))
        for ev in shown:
            self._list.addWidget(self._row(ev))

    def _row(self, ev: dict) -> ListRow:
        t = i18n.t
        state = self._segment
        tone = _STATE_TONE[state]
        color = {"accent": C["accent"], "green": C["green"], "neutral": C["text_dim"]}[tone]
        icon = ev.get("icon") if ev.get("icon") and icons.has(ev["icon"]) else _STATE_ICON[state]
        row = ListRow(event_title(ev), event_subtitle(ev), leading=_icon_chip(icon, color))
        row.trailing_box.addWidget(Pill(t(f"non_steam.state_{state}").upper(), tone), 0,
                                   Qt.AlignmentFlag.AlignVCenter)
        url = str(ev.get("url", ""))
        open_btn = Button(t("non_steam.open"), variant="ghost", icon="external",
                          on_click=lambda _=False, u=url: open_url(u))
        open_btn.setToolTip(url)
        row.trailing_box.addWidget(open_btn)
        row.clicked.connect(lambda u=url: open_url(u))
        row.setToolTip(url)
        return row


NonSteamFestivalsView = NonSteamView       # shell compatibility alias
