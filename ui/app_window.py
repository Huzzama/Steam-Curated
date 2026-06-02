import customtkinter as ctk
from config import COLORS, APP_NAME, WINDOW_SIZE, MIN_WINDOW_SIZE
import i18n

DETAIL_WIDTH = 320
NAV_ORDER    = ["wishlist", "dashboard", "deals", "history", "settings"]


class AppWindow(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry(WINDOW_SIZE)
        self.minsize(*MIN_WINDOW_SIZE)
        self.configure(fg_color=COLORS["bg"])

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._active_view = "wishlist"
        self._detail_open = False
        self._views: dict = {}

        self._build_layout()
        self._build_sidebar()
        # Single deferred start — runs once after window is realized
        self.after(50, self._start)

    # ── Layout ────────────────────────────────────────────────────

    def _build_layout(self):
        self._sidebar = ctk.CTkFrame(
            self, fg_color=COLORS["panel"], width=200, corner_radius=0,
        )
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        ctk.CTkFrame(
            self._sidebar, fg_color=COLORS["border"], width=1, corner_radius=0,
        ).pack(side="right", fill="y")

        self._right = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        self._right.pack(side="left", fill="both", expand=True)

        # Single shared container — views use pack/pack_forget
        self._container = ctk.CTkFrame(
            self._right, fg_color=COLORS["bg"], corner_radius=0,
        )
        self._container.pack(side="left", fill="both", expand=True)

        self._detail_container = ctk.CTkFrame(
            self._right,
            fg_color=COLORS["panel"],
            corner_radius=0,
            border_width=1,
            border_color=COLORS["border"],
            width=DETAIL_WIDTH,
        )
        self._detail_container.pack_propagate(False)

    # ── Sidebar ───────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = self._sidebar
        logo = ctk.CTkFrame(sb, fg_color="transparent", corner_radius=0, height=60)
        logo.pack(fill="x")
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="STEAM CURATOR",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["blue"]).pack(anchor="w", padx=16, pady=(16,0))
        ctk.CTkLabel(logo, text=i18n.t("app.subtitle"),
                     font=ctk.CTkFont(size=10),
                     text_color=COLORS["text_dim"]).pack(anchor="w", padx=16)
        ctk.CTkFrame(sb, fg_color=COLORS["border"], height=1, corner_radius=0).pack(fill="x")

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._nav_section(sb, i18n.t("nav_sections.collection"))
        self._nav_item(sb, "wishlist",  i18n.t("nav.wishlist"),  "♡")
        self._nav_section(sb, i18n.t("nav_sections.tools"))
        self._nav_item(sb, "dashboard", i18n.t("nav.dashboard"), "▦")
        self._nav_item(sb, "deals",     i18n.t("nav.deals"),     "🏷")
        self._nav_item(sb, "history",   i18n.t("nav.history"),   "◷")
        self._nav_item(sb, "settings",  i18n.t("nav.settings"),  "⚙")

    def _nav_section(self, parent, label: str):
        ctk.CTkLabel(parent, text=label.upper(),
                     font=ctk.CTkFont(size=9),
                     text_color=COLORS["text_dim"]).pack(anchor="w", padx=16, pady=(14,2))

    def _nav_item(self, parent, view_key: str, label: str, icon: str):
        btn = ctk.CTkButton(
            parent, text=f"  {icon}  {label}",
            anchor="w", height=38,
            fg_color="transparent", text_color=COLORS["text_dim"],
            hover_color=COLORS["card_hover"], corner_radius=6,
            font=ctk.CTkFont(size=13),
            command=lambda k=view_key: self._show_view(k),
        )
        btn.pack(fill="x", padx=8, pady=1)
        self._nav_buttons[view_key] = btn

    def _set_active_nav(self, key: str):
        for k, btn in self._nav_buttons.items():
            btn.configure(
                fg_color=COLORS["card_hover"] if k == key else "transparent",
                text_color=COLORS["blue"] if k == key else COLORS["text_dim"],
            )

    # ── Startup ───────────────────────────────────────────────────

    def _start(self):
        """Build and show wishlist. Only called once."""
        self._set_active_nav("wishlist")
        view = self._build_view("wishlist")
        view.pack(fill="both", expand=True)
        # Initial data load
        if hasattr(view, "refresh"):
            view.refresh()

    def _build_view(self, key: str):
        """Build a view once and cache it. Never rebuild."""
        if key in self._views:
            return self._views[key]

        from ui.wishlist_view import WishlistView
        from ui.dashboard_view import DashboardView
        from ui.deals_view import DealsView
        from ui.history_settings_views import HistoryView, SettingsView

        builders = {
            "wishlist":  lambda: WishlistView(self._container,
                             on_add_game=self._open_add_dialog,
                             on_game_click=self._open_detail),
            "dashboard": lambda: DashboardView(self._container),
            "deals":     lambda: DealsView(self._container,
                             on_game_click=self._open_detail),
            "history":   lambda: HistoryView(self._container,
                             on_game_click=self._open_detail),
            "settings":  lambda: SettingsView(self._container,
                             on_locale_change=self._on_locale_change),
        }
        view = builders[key]()
        self._views[key] = view
        return view

    # ── Navigation ────────────────────────────────────────────────

    def _show_view(self, key: str):
        if key == self._active_view:
            return

        # Hide current
        current = self._views.get(self._active_view)
        if current:
            current.pack_forget()

        self._active_view = key
        self._set_active_nav(key)
        self._close_detail()

        # Build if first visit, else reuse
        view = self._build_view(key)
        view.pack(fill="both", expand=True)

        # Refresh only on first show or if data changed (cheap — hash check inside)
        if hasattr(view, "refresh"):
            view.refresh()

    # ── Detail ────────────────────────────────────────────────────

    def _open_detail(self, game):
        from ui.game_detail_panel import GameDetailPanel
        if not hasattr(self, "_detail_panel"):
            self._detail_panel = GameDetailPanel(
                self._detail_container,
                on_close=self._close_detail,
                on_refresh=self._refresh_active,
            )
            self._detail_panel.pack(fill="both", expand=True)
        if not self._detail_open:
            self._detail_container.pack(side="right", fill="y")
            self._detail_open = True
        self._detail_panel.load_game(game)

    def _close_detail(self):
        if self._detail_open:
            self._detail_container.pack_forget()
            self._detail_open = False

    def _refresh_active(self):
        view = self._views.get(self._active_view)
        if view and hasattr(view, "refresh"):
            view.refresh()

    def _open_add_dialog(self):
        from ui.add_game_dialog import AddGameDialog
        AddGameDialog(self, on_success=self._refresh_active)

    # ── Locale ────────────────────────────────────────────────────

    def _on_locale_change(self):
        # Destroy all cached views — they'll rebuild with new locale
        for view in self._views.values():
            view.pack_forget()
            view.destroy()
        self._views.clear()
        self._nav_buttons.clear()
        for w in self._sidebar.winfo_children():
            w.destroy()
        self._build_sidebar()
        self._active_view = "wishlist"
        self.after(50, self._start)