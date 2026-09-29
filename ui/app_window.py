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

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QWidget

import i18n
from config import APP_NAME, MIN_WINDOW_SIZE, WINDOW_SIZE
from ui import icons
from ui.animations import FadingStack, slide_panel
from ui.components import Button, Divider, ToastHost, label, vbox
from ui.theme import C, SP

log = logging.getLogger("curator.shell")

SIDEBAR_WIDTH = 216
DETAIL_MIN, DETAIL_MAX = 340, 640
DETAIL_WIDTH  = DETAIL_MAX          # default = widest; the user can drag the left edge narrower
_WIDTH_KEY    = "detail_panel_width"   # (2.2's "detail_width" defaulted to 400 — ignored now)
MAIN_MIN_WIDTH = 460                # never squeeze the view under the panel below this
PRICE_WATCH_TICK_MS = 60 * 60 * 1000
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


class _PanelGrip(QWidget):
    """Thin handle on the detail panel's left edge; drag to resize the panel."""

    def __init__(self, on_drag: Callable[[int], None], on_release: Callable[[], None], parent=None):
        super().__init__(parent)
        self.setFixedWidth(6)
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self.setMouseTracking(True)
        self._on_drag, self._on_release = on_drag, on_release
        self._hover = self._dragging = False

    def enterEvent(self, e):
        self._hover = True; self.update()

    def leaveEvent(self, e):
        self._hover = False; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True; self.update()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._on_drag(int(e.globalPosition().x()))

    def mouseReleaseEvent(self, e):
        if self._dragging:
            self._dragging = False; self.update()
            self._on_release()

    def paintEvent(self, e):
        p = QPainter(self)
        color = QColor(C["accent"] if (self._hover or self._dragging) else C["border"])
        p.fillRect(0, 0, 2 if (self._hover or self._dragging) else 1, self.height(), color)


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
        self._detail_width = self._saved_detail_width()
        self._watch_timer: Optional[QTimer] = None
        self._alerts_timer: Optional[QTimer] = None      # debounced watchlist upload (Discord alerts)

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
        self._detail.setStyleSheet("QFrame[surface=\"panel\"] { border: none; border-radius: 0; }")
        self._detail_lay = QHBoxLayout(self._detail)
        self._detail_lay.setContentsMargins(0, 0, 0, 0)
        self._detail_lay.setSpacing(0)
        # the grip doubles as the panel's left border
        self._detail_lay.addWidget(_PanelGrip(self._drag_detail, self._save_detail_width))
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
        if getattr(self, "_detail_open", False) and getattr(self._detail, "_slide_anim", None) is None:
            self._set_detail_width(self._fit_detail_width(self._detail_width))

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
        self.schedule_alert_sync()
        self._dirty |= DATA_VIEWS
        if self._active in DATA_VIEWS:
            self.refresh_active(force=True)
        if self._detail_open and self._detail_panel is not None and hasattr(self._detail_panel, "reload"):
            self._detail_panel.reload()

    def on_locale_change(self) -> None:
        """Locale / country / currency changed in Settings."""
        self.schedule_alert_sync()
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
            slide_panel(self._detail, True, self._fit_detail_width(self._detail_width))

    def close_detail(self) -> None:
        if self._detail_open:
            self._detail_open = False
            slide_panel(self._detail, False, self._detail.width())

    @staticmethod
    def _saved_detail_width() -> int:
        from ui.settings_loader import get_settings
        try:
            w = int(get_settings().get(_WIDTH_KEY) or DETAIL_WIDTH)
        except (TypeError, ValueError):
            w = DETAIL_WIDTH
        return max(DETAIL_MIN, min(DETAIL_MAX, w))

    def _fit_detail_width(self, w: int) -> int:
        """Clamp to 340–640 and leave the main view at least MAIN_MIN_WIDTH."""
        room = self.width() - SIDEBAR_WIDTH - MAIN_MIN_WIDTH
        return max(DETAIL_MIN, min(DETAIL_MAX, w, room))

    def _set_detail_width(self, w: int) -> None:
        self._detail.setMinimumWidth(w)
        self._detail.setMaximumWidth(w)

    def _drag_detail(self, global_x: int) -> None:
        if not self._detail_open or getattr(self._detail, "_slide_anim", None) is not None:
            return
        right = self._detail.mapToGlobal(self._detail.rect().topRight()).x()
        self._detail_width = self._fit_detail_width(right - global_x)
        self._set_detail_width(self._detail_width)

    def _save_detail_width(self) -> None:
        from ui.settings_loader import save_settings
        try:
            save_settings({_WIDTH_KEY: int(self._detail_width)})
        except OSError as e:
            log.warning("detail width not saved: %s", e)

    # ── automatic price check (builds the deal history) ──────────────────────

    def start_price_watch(self, first_delay_ms: int = 8000) -> None:
        """Check wishlist prices now if the last check is ~a day old, then every hour
        re-evaluate. Called by main.py (not by the screenshot tool)."""
        if self._watch_timer is not None:
            return
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._maybe_check_prices)
        self._watch_timer.start(PRICE_WATCH_TICK_MS)
        QTimer.singleShot(first_delay_ms, self._maybe_check_prices)   # GUI thread → fine

    def _maybe_check_prices(self) -> None:
        from services import price_watch
        if price_watch.is_running() or not price_watch.is_due():
            return
        from ui.async_bridge import run_async

        def on_done(result):
            if isinstance(result, Exception):
                log.warning("price check failed: %s", result)
                return
            if result.get("skipped") or not result.get("checked"):
                return
            names = result.get("new_sales") or []
            if len(names) == 1:
                self.notify(i18n.t("watch.new_sale_one", name=names[0]), "success")
            elif names:
                shown = ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
                self.notify(i18n.t("watch.new_sale_other", n=len(names), names=shown), "success")
            self.on_data_changed()
            settings = self._views.get("settings")
            if settings is not None and hasattr(settings, "_render_price_tracking"):
                settings._render_price_tracking()

        run_async(self, price_watch.check_now, on_done=on_done)

    def start_purchase_sync(self, delay_ms: int = 12000) -> None:
        """Send purchases never sent to pimpmysteam.com (offline / older versions);
        the server verifies each one against the Steam library."""
        def run():
            from services import purchase_sync
            from ui.async_bridge import run_async

            def on_done(result):
                if isinstance(result, Exception):
                    log.info("purchase sync failed: %s", result)
                    return
                if result.get("sent"):
                    self.notify(i18n.t("verify.sync_done", n=result["sent"]), "info")
                    self.on_data_changed()
            run_async(self, purchase_sync.sync_pending, on_done=on_done)
        QTimer.singleShot(delay_ms, run)            # GUI thread → fine

    def schedule_alert_sync(self, delay_ms: int = 20000) -> None:
        """Upload the watchlist for Discord alerts a little after the last change
        (only happens while alerts are linked, and only if something changed)."""
        if self._alerts_timer is None:
            self._alerts_timer = QTimer(self)
            self._alerts_timer.setSingleShot(True)
            self._alerts_timer.timeout.connect(self._push_alert_watchlist)
        self._alerts_timer.start(delay_ms)

    def _push_alert_watchlist(self) -> None:
        from services import discord_alerts
        from services.steamkustom_auth import get_token
        if not get_token():
            return
        from ui.async_bridge import run_async
        run_async(self, discord_alerts.push_watchlist,
                  on_done=lambda r: log.info("alerts watchlist: %s", r))

    def start_update_check(self, delay_ms: int = 12000) -> None:
        """A little after start-up, ask GitHub (in a thread) whether there is a
        newer release; toast once per version. Settings › About shows it too."""
        QTimer.singleShot(delay_ms, self._check_updates)

    def _check_updates(self) -> None:
        from services import update_check
        from ui.async_bridge import run_async

        def on_done(result):
            if isinstance(result, Exception) or not result or not result.get("newer"):
                return
            from ui.settings_loader import get_settings, save_settings
            if get_settings().get("update_toasted") == result["latest"]:
                return                      # already announced this version
            save_settings({"update_toasted": result["latest"]})
            self.toasts.show(i18n.t("update.available", v=result["latest"]), "info", duration_ms=8000)
            view = self._views.get("settings")
            if view is not None and hasattr(view, "refresh_update_row"):
                view.refresh_update_row()
        run_async(self, update_check.check, on_done=on_done)

    # ── dialogs / toasts ─────────────────────────────────────────────────────

    def open_add_dialog(self) -> None:
        from ui.add_game_dialog import AddGameDialog
        dlg = AddGameDialog(self, on_success=self.on_data_changed)
        dlg.exec()

    def notify(self, message: str, tone: str = "info") -> None:
        self.toasts.show(message, tone)
