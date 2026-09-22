"""
Application shell: sidebar · animated view stack · slide-in detail panel ·
toast notifications.

Contract every view follows
---------------------------
    View(parent, **deps)            deps are callables the shell provides
    view.refresh(force=False)       (re)load data; force=True bypasses caches
    view.retranslate()              optional — update visible strings in place;
                                    views without it are rebuilt on locale change

Shell services views can call (passed as keyword deps, never imported):
    open_detail(game)  close_detail()  open_add_dialog()
    notify(message, tone)             toast: info | success | warning | error
    on_data_changed()                 games/purchases changed somewhere
    on_locale_change()                locale / currency / country changed
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget

import i18n
from config import APP_NAME, MIN_WINDOW_SIZE, WINDOW_SIZE
from ui import icons
from ui.animations import FadingStack, slide_panel
from ui.components import Button, Divider, ToastHost, label, vbox
from ui.theme import C, SP

log = logging.getLogger("curator.shell")

SIDEBAR_WIDTH = 216
DETAIL_WIDTH  = 340
_W, _H = (int(x) for x in WINDOW_SIZE.split("x"))

# sidebar order = slide direction between views
NAV_ORDER = ["wishlist", "library", "dashboard", "deals", "non_steam", "history", "recap", "settings"]
# views that show game / purchase data and go stale when it changes
DATA_VIEWS = {"wishlist", "library", "dashboard", "deals", "history", "recap"}

_NAV = [  # (section key or None, [(view key, icon)])
    ("nav_sections.collection", [("wishlist", "wishlist")]),
    ("nav_sections.tools", [("library", "library"), ("dashboard", "dashboard"), ("deals", "deals"),
                            ("non_steam", "non_steam"), ("history", "history"), ("recap", "recap")]),
]
_NEWS_URL = "https://pimpmysteam.com/news"


class Sidebar(QFrame):
    """Navigation rail. Emits nothing: the shell passes `on_select`."""

    def __init__(self, on_select: Callable[[str], None], parent=None):
        super().__init__(parent)
        self.setProperty("surface", "sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)
        self._on_select = on_select
        self._buttons: dict[str, Button] = {}
        self._sections: dict[str, QLabel] = {}

        lay = vbox(self, (SP["md"], SP["lg"], SP["md"], SP["md"]), SP["xs"])

        # brand
        brand = QWidget()
        bl = vbox(brand, (SP["sm"], 0, SP["sm"], SP["sm"]), 0)
        wordmark = label("STEAM CURATOR", family="display", size="2xl", color=C["text"])
        wordmark.setStyleSheet(wordmark.styleSheet() + " letter-spacing: 1px;")
        bl.addWidget(wordmark)
        self._subtitle = label("", role="eyebrow")
        bl.addWidget(self._subtitle)
        lay.addWidget(brand)
        lay.addSpacing(SP["sm"])

        for section_key, items in _NAV:
            sec = label("", role="eyebrow")
            sec.setContentsMargins(SP["sm"], SP["md"], 0, SP["xs"])
            self._sections[section_key] = sec
            lay.addWidget(sec)
            for key, icon in items:
                lay.addWidget(self._nav_button(key, icon))

        lay.addStretch()

        # footer: account · news · settings
        self._account = label("", role="muted", elide=True)
        self._account.setContentsMargins(SP["sm"], 0, SP["sm"], SP["xs"])
        lay.addWidget(self._account)
        self._news = Button("", variant="nav", icon="news",
                            on_click=lambda: QDesktopServices.openUrl(QUrl(_NEWS_URL)))
        self._news.setToolTip(_NEWS_URL)
        lay.addWidget(self._news)
        lay.addWidget(Divider())
        lay.addWidget(self._nav_button("settings", "settings"))

        self.retranslate()

    def _nav_button(self, key: str, icon: str) -> Button:
        btn = Button("", variant="nav", icon=icon, on_click=lambda: self._on_select(key))
        btn.setFixedHeight(36)
        btn.setProperty("active", "false")
        self._buttons[key] = btn
        return btn

    def set_active(self, key: str) -> None:
        for k, btn in self._buttons.items():
            active = k == key
            if (btn.property("active") == "true") != active:
                btn.setProperty("active", "true" if active else "false")
                btn.set_icon(btn._icon_name, C["accent"] if active else C["text_dim"])
                btn.style().unpolish(btn); btn.style().polish(btn)

    def set_account(self, username: Optional[str]) -> None:
        self._account.setText(username or "")
        self._account.setVisible(bool(username))

    def retranslate(self) -> None:
        self._subtitle.setText(i18n.t("app.subtitle").upper())
        for key, lbl in self._sections.items():
            lbl.setText(i18n.t(key).upper())
        for key, btn in self._buttons.items():
            btn.setText(i18n.t(f"nav.{key}"))
        self._news.setText(i18n.t("nav.news"))


class AppWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(_W, _H)
        self.setMinimumSize(*MIN_WINDOW_SIZE)

        self._views: dict[str, QWidget] = {}
        self._loaded: set[str] = set()     # views that have refreshed at least once
        self._dirty: set[str] = set()      # views whose data changed while hidden
        self._active: Optional[str] = None
        self._detail_open = False
        self._detail_panel = None

        self._build()
        self._shortcuts()
        self.toasts = ToastHost(self)
        self.show_view("wishlist")

    # ── layout ───────────────────────────────────────────────────────────────

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(self.show_view)
        root.addWidget(self.sidebar)

        self._stack = FadingStack()
        root.addWidget(self._stack, 1)

        self._detail = QFrame()
        self._detail.setProperty("surface", "panel")
        self._detail.setStyleSheet(f"QFrame[surface=\"panel\"] {{ border-left: 1px solid {C['border']}; "
                                   f"border-radius: 0; }}")
        self._detail_lay = QVBoxLayout(self._detail)
        self._detail_lay.setContentsMargins(0, 0, 0, 0)
        self._detail.setMaximumWidth(0)
        self._detail.hide()
        root.addWidget(self._detail)

        self._refresh_account()

    def _shortcuts(self) -> None:
        for i, key in enumerate(NAV_ORDER, start=1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, activated=lambda k=key: self.show_view(k))
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.open_add_dialog)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=lambda: self.refresh_active(force=True))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close_detail)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts.relayout()

    # ── views ────────────────────────────────────────────────────────────────

    def _deps(self) -> dict:
        return dict(open_detail=self.open_detail, close_detail=self.close_detail,
                    open_add_dialog=self.open_add_dialog, notify=self.notify,
                    on_data_changed=self.on_data_changed, on_locale_change=self.on_locale_change)

    def _make_view(self, key: str) -> QWidget:
        d = self._deps()
        if key == "wishlist":
            from ui.wishlist_view import WishlistView
            return WishlistView(self._stack, on_add_game=d["open_add_dialog"], on_game_click=d["open_detail"], **d)
        if key == "library":
            from ui.library_view import LibraryView
            return LibraryView(self._stack, **d)
        if key == "dashboard":
            from ui.dashboard_view import DashboardView
            return DashboardView(self._stack, **d)
        if key == "deals":
            from ui.deals_view import DealsView
            return DealsView(self._stack, on_game_click=d["open_detail"], **d)
        if key == "non_steam":
            from ui.non_steam_view import NonSteamView
            return NonSteamView(self._stack, **d)
        if key == "history":
            from ui.history_view import HistoryView
            return HistoryView(self._stack, on_game_click=d["open_detail"], **d)
        if key == "recap":
            from ui.recap_view import RecapView
            return RecapView(self._stack, **d)
        if key == "settings":
            from ui.settings_view import SettingsView
            return SettingsView(self._stack, **d)
        raise KeyError(key)

    def view(self, key: str) -> Optional[QWidget]:
        """Already-built view or None (never builds)."""
        return self._views.get(key)

    def _get_view(self, key: str) -> QWidget:
        v = self._views.get(key)
        if v is None:
            v = self._make_view(key)
            v.setProperty("shell", self)
            self._views[key] = v
            self._stack.addWidget(v)
        return v

    @staticmethod
    def _call_refresh(view: QWidget, force: bool) -> None:
        fn = getattr(view, "refresh", None)
        if fn is None:
            return
        try:
            fn(force=force)
        except TypeError:          # legacy views without the kwarg
            fn()
        except Exception:          # noqa: BLE001
            log.exception("refresh failed for %s", type(view).__name__)

    def show_view(self, key: str) -> None:
        if key == self._active:
            return
        prev = self._active
        view = self._get_view(key)

        if key not in self._loaded or key in self._dirty:
            self._call_refresh(view, force=False)
            self._loaded.add(key)
            self._dirty.discard(key)

        direction = 0
        if prev in NAV_ORDER and key in NAV_ORDER:
            direction = 1 if NAV_ORDER.index(key) > NAV_ORDER.index(prev) else -1
        self._active = key
        self.sidebar.set_active(key)
        self.close_detail()
        self._stack.set_current(view, direction)

    def refresh_active(self, force: bool = False) -> None:
        if self._active and self._active in self._views:
            self._call_refresh(self._views[self._active], force=force)
            self._loaded.add(self._active)
            self._dirty.discard(self._active)

    # ── data / locale events ─────────────────────────────────────────────────

    def on_data_changed(self) -> None:
        """Games or purchases changed: refresh the visible view now, others lazily."""
        self._dirty |= DATA_VIEWS
        if self._active in DATA_VIEWS:
            self.refresh_active(force=True)
        if self._detail_open and self._detail_panel is not None and hasattr(self._detail_panel, "reload"):
            self._detail_panel.reload()

    def on_locale_change(self) -> None:
        """Locale / country / currency changed in Settings."""
        self.setWindowTitle(APP_NAME)
        self.sidebar.retranslate()
        self._refresh_account()
        for key, v in list(self._views.items()):
            if hasattr(v, "retranslate"):
                v.retranslate()
                self._dirty.add(key)          # prices/currency may have changed too
            elif key != self._active:
                self._drop_view(key)
            else:
                self._dirty.add(key)
        if self._detail_panel is not None:
            self.close_detail()
            self._detail_panel.setParent(None)
            self._detail_panel.deleteLater()
            self._detail_panel = None
        self.refresh_active(force=True)

    def _drop_view(self, key: str) -> None:
        v = self._views.pop(key, None)
        if v is not None:
            self._stack.removeWidget(v)
            v.setParent(None)
            v.deleteLater()
        self._loaded.discard(key)
        self._dirty.discard(key)

    def _refresh_account(self) -> None:
        try:
            from services import steamkustom_auth as acct
            self.sidebar.set_account(acct.get_username() if acct.is_connected() else None)
        except Exception:  # noqa: BLE001
            self.sidebar.set_account(None)

    # ── detail panel ─────────────────────────────────────────────────────────

    def open_detail(self, game) -> None:
        if self._detail_panel is None:
            from ui.game_detail_panel import GameDetailPanel
            self._detail_panel = GameDetailPanel(self._detail, on_close=self.close_detail,
                                                 on_refresh=self.on_data_changed, notify=self.notify)
            self._detail_lay.addWidget(self._detail_panel)
        self._detail_panel.load_game(game)
        if not self._detail_open:
            self._detail_open = True
            slide_panel(self._detail, True, DETAIL_WIDTH)

    def close_detail(self) -> None:
        if self._detail_open:
            self._detail_open = False
            slide_panel(self._detail, False, DETAIL_WIDTH)

    # ── dialogs / toasts ─────────────────────────────────────────────────────

    def open_add_dialog(self) -> None:
        from ui.add_game_dialog import AddGameDialog
        dlg = AddGameDialog(self, on_success=self.on_data_changed)
        dlg.exec()

    def notify(self, message: str, tone: str = "info") -> None:
        self.toasts.show(message, tone)
