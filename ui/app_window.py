from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedLayout,
    QFrame, QLabel, QPushButton,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from config import COLORS, APP_NAME, WINDOW_SIZE, MIN_WINDOW_SIZE
import i18n
from ui.animations import safe_show_view, slide_in_right, slide_out_right, nav_click_feedback, clear_layout

DETAIL_WIDTH = 320
_W, _H       = (int(x) for x in WINDOW_SIZE.split("x"))
_MIN_W, _MIN_H = MIN_WINDOW_SIZE


class AppWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(_W, _H)
        self.setMinimumSize(_MIN_W, _MIN_H)

        self._active_view = "wishlist"
        self._detail_open = False
        self._views: dict  = {}
        self._nav_buttons: dict = {}

        # Dirty-flag system: views are only refreshed when their data changed
        # or when they are shown for the first time.
        self._initialized_views: set = set()
        self._dirty_views:       set = set()

        self._build_layout()
        self._build_sidebar()
        QTimer.singleShot(50, self._start)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self):
        central = QWidget()
        central.setStyleSheet(f"background:{COLORS['bg']};")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar — fixed outer frame, inner content is replaced on locale change
        self._sidebar = QFrame()
        self._sidebar.setFixedWidth(200)
        self._sidebar.setStyleSheet(f"""
            QFrame#sidebar {{
                background:{COLORS['panel']};
                border-right:1px solid {COLORS['border']};
            }}
        """)
        self._sidebar.setObjectName("sidebar")
        # Permanent layout with a single slot for the inner widget
        sb_lay = QVBoxLayout(self._sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(0)
        root.addWidget(self._sidebar)

        # Right area
        right = QWidget()
        right.setStyleSheet(f"background:{COLORS['bg']};")
        right_lay = QHBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        root.addWidget(right, 1)

        # View container — NO layout manager so slide_transition can freely
        # animate widget positions with setGeometry/move without a layout
        # fighting the animation and causing flicker.
        self._container = QWidget()
        self._container.setStyleSheet(f"background:{COLORS['bg']};")
        right_lay.addWidget(self._container, 1)

        # Detail panel
        self._detail_container = QFrame()
        self._detail_container.setFixedWidth(DETAIL_WIDTH)
        self._detail_container.setStyleSheet(f"""
            QFrame {{
                background:{COLORS['panel']};
                border-left:1px solid {COLORS['border']};
            }}
        """)
        self._detail_container_lay = QVBoxLayout(self._detail_container)
        self._detail_container_lay.setContentsMargins(0, 0, 0, 0)
        self._detail_container.hide()
        right_lay.addWidget(self._detail_container)

    # ── Resize: keep views filling container ─────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "_container"):
            return
        rect = self._container.rect()
        for view in self._views.values():
            # Don't resize while a slide animation is in progress
            if not getattr(view, "_slide_anim", None):
                try:
                    view.setGeometry(rect)
                except RuntimeError:
                    pass

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        """Build sidebar content into a fresh inner widget."""
        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Logo
        logo = QWidget()
        logo.setFixedHeight(60)
        ll = QVBoxLayout(logo)
        ll.setContentsMargins(16, 16, 16, 0)
        ll.setSpacing(2)

        title = QLabel("STEAM CURATOR")
        title.setFont(QFont("Space Mono", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{COLORS['blue']};")
        ll.addWidget(title)

        subtitle = QLabel(i18n.t("app.subtitle"))
        subtitle.setFont(QFont("Space Mono", 10))
        subtitle.setStyleSheet(f"color:{COLORS['text_dim']};")
        ll.addWidget(subtitle)
        lay.addWidget(logo)

        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"color:{COLORS['border']};"); div.setFixedHeight(1)
        lay.addWidget(div)

        self._nav_buttons = {}
        self._nav_section(lay, i18n.t("nav_sections.collection"))
        self._nav_item(lay, "wishlist",  i18n.t("nav.wishlist"),  "♡")
        self._nav_section(lay, i18n.t("nav_sections.tools"))
        self._nav_item(lay, "library",   i18n.t("nav.library"),   "📚")
        self._nav_item(lay, "dashboard", i18n.t("nav.dashboard"), "▦")
        self._nav_item(lay, "deals",     i18n.t("nav.deals"),     "🏷")
        self._nav_item(lay, "non_steam", i18n.t("nav.non_steam"), "🌐")
        self._nav_item(lay, "history",   i18n.t("nav.history"),   "◷")
        self._nav_item(lay, "recap",     i18n.t("nav.recap"),     "✦")
        lay.addStretch()

        # News button — opens pimpmysteam.com/news in external browser
        self._nav_section(lay, "PIMPMYSTEAM")
        self._nav_external(lay, "https://pimpmysteam.com/news", i18n.t("nav.news"), "📰")

        div2 = QFrame(); div2.setFrameShape(QFrame.Shape.HLine)
        div2.setStyleSheet(f"color:{COLORS['border']};"); div2.setFixedHeight(1)
        lay.addWidget(div2)

        self._nav_item(lay, "settings",  i18n.t("nav.settings"),  "⚙")

        # Add to sidebar layout
        self._sidebar.layout().addWidget(inner)
        self._sidebar_inner = inner

    def _clear_sidebar(self):
        """Remove all widgets from sidebar layout — synchronous."""
        sb_lay = self._sidebar.layout()
        while sb_lay.count():
            item = sb_lay.takeAt(0)
            w = item.widget()
            if w:
                # setParent(None) immediately removes from layout AND destroys
                w.hide()
                w.setParent(None)
                # Don't call deleteLater — setParent(None) is enough for GC

    def _nav_section(self, lay, label: str):
        lbl = QLabel(label.upper())
        lbl.setFont(QFont("Space Mono", 9))
        lbl.setStyleSheet(f"color:{COLORS['text_dim']};")
        lbl.setContentsMargins(16, 14, 0, 2)
        lay.addWidget(lbl)

    def _nav_item(self, lay, view_key: str, label: str, icon: str):
        btn = QPushButton(f"  {icon}  {label}")
        btn.setFixedHeight(38)
        btn.setFont(QFont("Space Mono", 13))
        btn.setCheckable(True)
        btn.setStyleSheet(self._nav_style(False))
        btn.clicked.connect(lambda _, k=view_key: (
            nav_click_feedback(btn), self._show_view(k)))

        w = QWidget(); w.setStyleSheet("background:transparent;")
        wl = QHBoxLayout(w)
        wl.setContentsMargins(8, 1, 8, 1)
        wl.addWidget(btn)
        lay.addWidget(w)
        self._nav_buttons[view_key] = btn

    def _nav_external(self, lay, url: str, label: str, icon: str):
        """Nav button that opens an external URL in the system browser."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        btn = QPushButton(f"  {icon}  {label}  ↗")
        btn.setFixedHeight(38)
        btn.setFont(QFont("Space Mono", 13))
        btn.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{COLORS['text_dim']};
                border:none; border-radius:6px;
                text-align:left; padding-left:8px;
                font-family:'Space Mono'; font-size:13px;
            }}
            QPushButton:hover {{
                background:{COLORS['card_hover']}; color:{COLORS['blue']};
            }}
        """)
        btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))

        w = QWidget(); w.setStyleSheet("background:transparent;")
        wl = QHBoxLayout(w)
        wl.setContentsMargins(8, 1, 8, 1)
        wl.addWidget(btn)
        lay.addWidget(w)

    def _nav_style(self, active: bool) -> str:
        bg = COLORS["card_hover"] if active else "transparent"
        fg = COLORS["blue"]       if active else COLORS["text_dim"]
        return f"""
            QPushButton {{
                background:{bg}; color:{fg};
                border:none; border-radius:6px;
                text-align:left; padding-left:8px;
                font-family:'Space Mono'; font-size:13px;
            }}
            QPushButton:hover {{
                background:{COLORS['card_hover']}; color:{COLORS['text']};
            }}
        """

    def _set_active_nav(self, key: str):
        for k, btn in self._nav_buttons.items():
            btn.setChecked(k == key)
            btn.setStyleSheet(self._nav_style(k == key))

    # ── Startup ───────────────────────────────────────────────────────────────

    def _start(self):
        self._set_active_nav("wishlist")
        view = self._build_view("wishlist")
        view.setGeometry(self._container.rect())
        view.show()
        if hasattr(view, "refresh"):
            view.refresh()
        self._initialized_views.add("wishlist")

    def _build_view(self, key: str):
        if key in self._views:
            return self._views[key]

        from ui.wishlist_view          import WishlistView
        from ui.dashboard_view         import DashboardView
        from ui.deals_view             import DealsView
        from ui.history_settings_views import HistoryView, SettingsView

        builders = {
            "wishlist":  lambda: WishlistView(self._container,
                             on_add_game=self._open_add_dialog,
                             on_game_click=self._open_detail),
            "library":   lambda: __import__("ui.library_view",
                             fromlist=["LibraryView"]).LibraryView(self._container),
            "dashboard": lambda: DashboardView(self._container),
            "deals":     lambda: DealsView(self._container,
                             on_game_click=self._open_detail),
            "non_steam": lambda: __import__(
                             "ui.nonstema_festivals_view",
                             fromlist=["NonSteamFestivalsView"]
                             ).NonSteamFestivalsView(self._container),
            "history":   lambda: HistoryView(self._container,
                             on_game_click=self._open_detail),
            "recap":     lambda: __import__("ui.recap_view",
                             fromlist=["RecapView"]).RecapView(self._container),
            "settings":  lambda: SettingsView(self._container,
                             on_locale_change=self._on_locale_change),
        }
        view = builders[key]()
        # Parent the view to the container without a layout — positions are
        # managed manually so slide_transition can animate freely.
        view.setParent(self._container)
        # Give the view its real geometry immediately — on macOS, views built
        # while hidden and never resized before being shown get 0x0 geometry,
        # which means scroll areas and charts never paint.
        rect = self._container.rect()
        if rect.width() == 0 or rect.height() == 0:
            from PySide6.QtCore import QRect
            rect = QRect(0, 0, _MIN_W, _MIN_H)
        view.setGeometry(rect)
        view.hide()
        self._views[key] = view
        return view

    # ── Navigation ────────────────────────────────────────────────────────────

    def _mark_dirty(self, *keys: str) -> None:
        """Mark views as needing a refresh next time they are shown."""
        for k in keys:
            self._dirty_views.add(k)

    def _refresh_view_if_needed(self, key: str, view) -> None:
        """Refresh a view only if it's new or its data changed."""
        if key not in self._initialized_views or key in self._dirty_views:
            if hasattr(view, "refresh"):
                try:
                    view.refresh()
                except Exception:
                    pass
            self._initialized_views.add(key)
            self._dirty_views.discard(key)

    def _show_view(self, key: str):
        if key == self._active_view:
            return
        prev_key = self._active_view
        current  = self._views.get(prev_key)

        view = self._build_view(key)

        # Refresh BEFORE animation — data must be ready when view becomes visible.
        # Refresh only runs when the view is new or has been marked dirty.
        self._refresh_view_if_needed(key, view)

        self._active_view = key
        self._set_active_nav(key)
        self._close_detail()

        # Pure animation — no data logic inside
        safe_show_view(current, view,
                       from_key=prev_key, to_key=key,
                       duration=260)

        # macOS: force a repaint after the animation so the new view
        # is never left blank due to a missed expose event.
        import sys as _sys
        if _sys.platform == "darwin":
            from PySide6.QtCore import QTimer as _QTimer
            _QTimer.singleShot(280, lambda: (
                view.update() if not view.isHidden() else None
            ))

    # ── Detail panel ──────────────────────────────────────────────────────────

    def _open_detail(self, game):
        from ui.game_detail_panel import GameDetailPanel
        if not hasattr(self, "_detail_panel"):
            self._detail_panel = GameDetailPanel(
                self._detail_container,
                on_close=self._close_detail,
                on_refresh=self._refresh_active,
            )
            self._detail_container_lay.addWidget(self._detail_panel)
        self._detail_panel.load_game(game)
        if not self._detail_open:
            self._detail_open = True
            slide_in_right(self._detail_container, DETAIL_WIDTH, duration=220)

    def _close_detail(self):
        if self._detail_open:
            self._detail_open = False
            slide_out_right(self._detail_container, duration=180)

    def _refresh_active(self):
        """Refresh the currently visible view immediately (forced)."""
        view = self._views.get(self._active_view)
        if not view:
            return
        try:
            if hasattr(view, "reload_after_change"):
                view.reload_after_change()
            elif hasattr(view, "refresh"):
                view.refresh(force=True)
        except Exception:
            pass

    def _open_add_dialog(self):
        from ui.add_game_dialog import AddGameDialog
        def _on_add_success():
            print("Game added — forcing wishlist reload")
            # Immediately refresh the active view (wishlist), bypassing the
            # "did anything change" check so the new game appears right away.
            self._refresh_active()
            # Mark all views that depend on game data as dirty
            self._mark_dirty("dashboard", "deals", "recap", "library", "history")
        dlg = AddGameDialog(self, on_success=_on_add_success)
        dlg.exec()

    # ── Locale / Country change ───────────────────────────────────────────────

    def _on_locale_change(self):
        """Called after settings saves. Rebuilds everything with new locale/currency."""
        # 1. Destroy all cached views and reset dirty-flag tracking
        for view in self._views.values():
            view.hide()
            view.setParent(None)
            view.deleteLater()
        self._views.clear()
        self._initialized_views.clear()
        self._dirty_views.clear()

        # 2. Close detail panel
        self._close_detail()
        if hasattr(self, "_detail_panel"):
            self._detail_panel.setParent(None)
            self._detail_panel.deleteLater()
            del self._detail_panel

        # 3. Rebuild sidebar cleanly
        self._clear_sidebar()
        self._nav_buttons.clear()

        self._active_view = "wishlist"

        # 4. Rebuild sidebar synchronously (no deleteLater in _clear_sidebar)
        self._build_sidebar()
        self._set_active_nav("wishlist")
        QTimer.singleShot(50, self._start)