"""
WishlistView — single-pipeline rendering.

Cards are created once in a fixed pool and reused.
On refresh: data is updated in existing widgets, no destroy/recreate.
Images load via LRU cache — disk only on first access.
"""
import customtkinter as ctk
from typing import Callable
from config import COLORS, PRIORITY_OPTIONS
from data.models import Game
from ui.widgets import StatCard, SteamButton, SectionHeader
import data.repository as repo
import i18n

COLS     = 6
MAX_ROWS = 12   # max rows per priority group = 72 cards total


class WishlistView(ctk.CTkFrame):

    def __init__(self, parent, on_add_game: Callable, on_game_click: Callable, **kwargs):
        super().__init__(parent, fg_color=COLORS["bg"], **kwargs)
        self.on_add_game   = on_add_game
        self.on_game_click = on_game_click
        self._games: list[Game]  = []
        self._filter             = "all"
        self._search_var         = ctk.StringVar()
        self._last_rendered_ids  = []   # detect actual changes
        self._built              = False
        self._build()

    # ─────────────────────────────────────────────────────────────
    # Build once
    # ─────────────────────────────────────────────────────────────

    def _build(self):
        # ── Topbar ───────────────────────────────────────────────
        topbar = ctk.CTkFrame(self, fg_color=COLORS["panel"],
                              corner_radius=0, height=52)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        ctk.CTkLabel(topbar, text=i18n.t("nav.wishlist"),
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left", padx=18)

        ctk.CTkEntry(topbar, textvariable=self._search_var,
                     placeholder_text=i18n.t("actions.search"),
                     width=200, height=30,
                     fg_color=COLORS["card"], border_color=COLORS["border"],
                     text_color=COLORS["text"]).pack(side="left", padx=(0,10), pady=10)
        self._search_var.trace_add("write", lambda *_: self._apply_filter())

        # Filter tabs
        ff = ctk.CTkFrame(topbar, fg_color="transparent")
        ff.pack(side="left")
        self._filter_btns: dict = {}
        for key, label in [("all", i18n.t("filters.all")),
                           ("S","S"),("A","A"),("B","B"),("C","C"),
                           ("sale", i18n.t("filters.on_sale"))]:
            btn = ctk.CTkButton(
                ff, text=label, width=46, height=28,
                fg_color=COLORS["blue"] if key=="all" else "transparent",
                text_color="#000" if key=="all" else COLORS["text_dim"],
                hover_color=COLORS["card_hover"],
                border_color=COLORS["border"], border_width=1,
                corner_radius=5, font=ctk.CTkFont(size=11),
                command=lambda k=key: self._set_filter(k),
            )
            btn.pack(side="left", padx=2)
            self._filter_btns[key] = btn

        # Right buttons
        SteamButton(topbar, text=i18n.t("actions.export"),
                    command=self._export_excel, style="ghost",
                    height=30, width=110).pack(side="right", padx=(0,6), pady=10)

        self._covers_btn = SteamButton(topbar, text="⬇ Covers",
                    command=self._download_covers, style="ghost",
                    height=30, width=90)
        self._covers_btn.pack(side="right", padx=(0,4), pady=10)

        self._covers_lbl = ctk.CTkLabel(topbar, text="",
                    font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"])
        self._covers_lbl.pack(side="right", padx=(0,4))

        SteamButton(topbar, text=f"+ {i18n.t('actions.add')}",
                    command=self.on_add_game,
                    height=30, width=120).pack(side="right", padx=(0,8), pady=10)

        # ── Stats row ────────────────────────────────────────────
        sf = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        sf.pack(fill="x", padx=14, pady=(10,0))
        self._stats: dict = {}
        for key, label, icon, accent in [
            ("total",   i18n.t("stats.total_games"), "◈", COLORS["blue"]),
            ("value",   i18n.t("stats.total_value"),  "◎", "#94a3b8"),
            ("savings", i18n.t("stats.savings"),      "↓", COLORS["green"]),
            ("s_count", i18n.t("stats.priority_s"),   "★", COLORS["gold"]),
            ("on_sale", i18n.t("stats.on_sale_now"),  "⚡", "#f472b6"),
        ]:
            c = StatCard(sf, label=label, value="—",
                         icon=icon, accent=accent)
            c.pack(side="left", fill="x", expand=True, padx=(0,6))
            self._stats[key] = c

        # ── Empty label ──────────────────────────────────────────
        self._empty_lbl = ctk.CTkLabel(
            self, text="No games match the filter.",
            font=ctk.CTkFont(size=13), text_color=COLORS["text_dim"],
        )

        # ── Scrollable area ──────────────────────────────────────
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=COLORS["bg"], corner_radius=0,
        )
        self._scroll.pack(fill="both", expand=True, padx=14, pady=10)

        # ── Card pool — built once, reused forever ────────────────
        # Structure: {priority: [row_frame, [_GameCard, ...]]}
        self._pool: dict[str, list] = {}
        self._section_labels: dict[str, ctk.CTkLabel] = {}

        for priority in ("S", "A", "B", "C"):
            # Section header label (hidden until needed)
            lbl = ctk.CTkLabel(self._scroll,
                               text=i18n.t(f"priority.{priority}"),
                               font=ctk.CTkFont(size=11, weight="bold"),
                               text_color=COLORS["text_dim"])
            self._section_labels[priority] = lbl

            # Pre-create MAX_ROWS * COLS cards per priority
            rows: list[tuple] = []   # (row_frame, [cards])
            for _ in range(MAX_ROWS):
                row_f = ctk.CTkFrame(self._scroll, fg_color="transparent")
                cards = []
                for col in range(COLS):
                    card = _GameCard(row_f, on_click=self.on_game_click)
                    card.grid(row=0, column=col, padx=4, pady=2, sticky="nw")
                    cards.append(card)
                rows.append((row_f, cards))
            self._pool[priority] = rows

        self._built = True

    # ─────────────────────────────────────────────────────────────
    # Refresh — updates data in existing widgets
    # ─────────────────────────────────────────────────────────────

    def refresh(self):
        if not self._built:
            return
        self._games = repo.get_all()
        self._update_stats()
        # Only re-render grid if game list actually changed
        new_ids = [(g.id, g.priority, g.cover_path) for g in self._games]
        if new_ids != self._last_rendered_ids:
            self._last_rendered_ids = new_ids
            self._apply_filter()

    def _update_stats(self):
        games    = self._games
        total    = len(games)
        on_sale  = sum(1 for g in games if g.price and g.price.is_on_sale)
        s_count  = sum(1 for g in games if g.priority == "S")
        currency = next((g.price.currency for g in games if g.price), "")
        total_v  = sum(g.price.current for g in games if g.price)
        savings  = sum(g.price.base - g.price.current for g in games
                       if g.price and g.price.is_on_sale
                       and g.price.base > g.price.current)
        self._stats["total"].set_value(str(total))
        self._stats["value"].set_value(f"${total_v:,.0f}{' '+currency if currency else ''}")
        self._stats["savings"].set_value(f"${savings:,.0f}")
        self._stats["s_count"].set_value(str(s_count))
        self._stats["on_sale"].set_value(str(on_sale))

    # ─────────────────────────────────────────────────────────────
    # Filter
    # ─────────────────────────────────────────────────────────────

    def _set_filter(self, key: str):
        self._filter = key
        for k, btn in self._filter_btns.items():
            btn.configure(
                fg_color=COLORS["blue"] if k==key else "transparent",
                text_color="#000" if k==key else COLORS["text_dim"],
            )
        self._apply_filter()

    def _apply_filter(self):
        q     = self._search_var.get().lower()
        games = self._games
        if self._filter == "sale":
            games = [g for g in games if g.price and g.price.is_on_sale]
        elif self._filter in ("S","A","B","C"):
            games = [g for g in games if g.priority == self._filter]
        if q:
            games = [g for g in games
                     if q in g.name.lower() or q in g.genre.lower()]
        self._layout(games)

    # ─────────────────────────────────────────────────────────────
    # Layout — assign games to pool cards, show/hide rows
    # ─────────────────────────────────────────────────────────────

    def _layout(self, games: list[Game]):
        """
        Update card pool in-place. No widgets created or destroyed.
        Only configure() calls on existing widgets.
        """
        has_any = bool(games)

        # Hide/show empty label
        if has_any:
            self._empty_lbl.pack_forget()
        else:
            self._empty_lbl.pack(pady=40)

        images_to_load = []   # (card, cover_path) — deferred

        for priority in ("S", "A", "B", "C"):
            group = [g for g in games if g.priority == priority]
            rows  = self._pool[priority]
            lbl   = self._section_labels[priority]

            if not group:
                # Hide section
                lbl.pack_forget()
                for row_f, cards in rows:
                    row_f.pack_forget()
                    for card in cards:
                        card.hide()
                continue

            # Show section label
            lbl.pack(anchor="w", pady=(12,4))

            needed_rows = (len(group) + COLS - 1) // COLS

            for row_idx, (row_f, cards) in enumerate(rows):
                if row_idx >= needed_rows:
                    row_f.pack_forget()
                    for card in cards:
                        card.hide()
                    continue

                row_f.pack(fill="x", pady=(0,4))
                row_start = row_idx * COLS

                for col, card in enumerate(cards):
                    game_idx = row_start + col
                    if game_idx < len(group):
                        game = group[game_idx]
                        card.show(game)
                        images_to_load.append((card, game.cover_path))
                    else:
                        card.hide()

        # Load images in one deferred batch — doesn't block layout
        self.after(10, lambda imgs=images_to_load: self._load_images(imgs))

    def _load_images(self, items: list):
        """Load all images at once via cache — single pass, no timers."""
        from ui.image_cache import get as img_get
        for card, cover_path in items:
            try:
                img = img_get(cover_path, (_GameCard.CARD_W - 4, _GameCard.IMG_H))
                card.set_image(img)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────

    def _download_covers(self):
        from services.steamgriddb import download_all_missing, cover_exists
        from ui.settings_loader import get_settings
        settings = get_settings()
        missing  = sum(1 for g in self._games if not cover_exists(g.app_id))
        if missing == 0:
            self._covers_lbl.configure(text="✓ All done", text_color=COLORS["green"])
            self.after(3000, lambda: self._covers_lbl.configure(text=""))
            return
        self._covers_btn.configure(state="disabled")
        self._covers_lbl.configure(text=f"0/{missing}", text_color=COLORS["blue"])

        def _prog(cur, tot, _name):
            self.after(0, lambda c=cur,t=tot:
                self._covers_lbl.configure(text=f"{c}/{t}"))

        def _done(dl, fail):
            def _upd():
                self._covers_btn.configure(state="normal")
                self._covers_lbl.configure(
                    text=f"✓{dl}" if not fail else f"✓{dl} ✗{fail}",
                    text_color=COLORS["green"] if not fail else COLORS["gold"],
                )
                from ui.image_cache import clear
                clear()
                self._last_rendered_ids = []
                self.refresh()
                self.after(4000, lambda: self._covers_lbl.configure(text=""))
            self.after(0, _upd)

        download_all_missing(
            self._games, settings.get("steamgriddb_key",""),
            on_progress=_prog, on_done=_done, max_workers=4,
        )

    def _export_excel(self):
        import threading
        from data.excel_manager import export_excel
        threading.Thread(target=export_excel, daemon=True).start()


# ─────────────────────────────────────────────────────────────────
# Reusable card — configure() only, never recreated
# ─────────────────────────────────────────────────────────────────

class _GameCard(ctk.CTkFrame):
    CARD_W = 148
    IMG_H  = 200

    def __init__(self, parent, on_click: Callable, **kwargs):
        super().__init__(parent,
                         fg_color=COLORS["card"],
                         corner_radius=8,
                         border_width=1,
                         border_color=COLORS["border"],
                         width=self.CARD_W, **kwargs)
        self.pack_propagate(False)
        self._on_click = on_click
        self._game     = None
        self._visible  = False
        self._build()

    def _build(self):
        from config import PRIORITY_COLORS

        # Invisible click overlay
        self._click_btn = ctk.CTkButton(
            self, text="", fg_color="transparent",
            hover_color=COLORS["card_hover"], corner_radius=8,
            command=self._click,
        )
        self._click_btn.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Cover image placeholder
        self._img_lbl = ctk.CTkLabel(
            self, text="", fg_color=COLORS["card_hover"],
            width=self.CARD_W-4, height=self.IMG_H,
        )
        self._img_lbl.pack(fill="x", padx=2, pady=(2,0))
        self._img_lbl.bind("<Button-1>", lambda e: self._click())

        # Priority badge
        self._badge = ctk.CTkLabel(
            self._img_lbl, text="",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=COLORS["border"],
            text_color=COLORS["text"],
            corner_radius=4, width=20, height=20,
        )
        self._badge.place(relx=1.0, rely=0.0, anchor="ne", x=-4, y=4)
        self._badge.bind("<Button-1>", lambda e: self._click())

        # Info strip
        info = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=0)
        info.pack(fill="x", padx=6, pady=(3,6))
        info.bind("<Button-1>", lambda e: self._click())

        self._name_lbl = ctk.CTkLabel(
            info, text="", anchor="w",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLORS["text"],
            wraplength=136, justify="left",
        )
        self._name_lbl.pack(anchor="w")
        self._name_lbl.bind("<Button-1>", lambda e: self._click())

        self._meta_lbl = ctk.CTkLabel(
            info, text="", anchor="w",
            font=ctk.CTkFont(size=9),
            text_color=COLORS["text_dim"],
        )
        self._meta_lbl.pack(anchor="w")
        self._meta_lbl.bind("<Button-1>", lambda e: self._click())

        pr = ctk.CTkFrame(info, fg_color="transparent")
        pr.pack(fill="x", pady=(2,0))
        pr.bind("<Button-1>", lambda e: self._click())

        self._price_lbl = ctk.CTkLabel(pr, text="",
                          font=ctk.CTkFont(size=10, weight="bold"),
                          text_color=COLORS["text"])
        self._price_lbl.pack(side="left")
        self._price_lbl.bind("<Button-1>", lambda e: self._click())

        self._dot_lbl = ctk.CTkLabel(pr, text="",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color=COLORS["text_dim"])
        self._dot_lbl.pack(side="right")
        self._dot_lbl.bind("<Button-1>", lambda e: self._click())

    def _click(self):
        if self._game:
            self._on_click(self._game)

    def show(self, game: Game):
        """Update card data without recreating any widget."""
        from config import PRIORITY_COLORS
        self._game    = game
        self._visible = True

        # Reset image to placeholder (real image loaded separately)
        self._img_lbl.configure(image=None, fg_color=COLORS["card_hover"])

        # Badge
        badge_color = PRIORITY_COLORS.get(game.priority, COLORS["border"])
        txt_color   = "#1a0f00" if game.priority == "S" else "#fff"
        self._badge.configure(text=game.priority,
                              fg_color=badge_color, text_color=txt_color)

        # Name + meta
        self._name_lbl.configure(text=game.name)
        meta = f"{game.release_year or '—'} · {game.genre.split(',')[0] if game.genre else '—'}"
        self._meta_lbl.configure(text=meta)

        # Price
        if game.price:
            price_color = COLORS["green"] if game.price.is_on_sale else COLORS["text"]
            self._price_lbl.configure(
                text=f"${game.price.current:,.0f}", text_color=price_color,
            )
        else:
            self._price_lbl.configure(text="—", text_color=COLORS["text_dim"])

        # Recommendation dot
        rec = game.buy_recommendation
        if any(x in rec for x in ("Comprar ahora","Buy now","今すぐ","Comprar agora","Acheter")):
            dot, dot_c = "✓", COLORS["green"]
        elif any(x in rec for x in ("cercano","Close","近","Perto","Proche")):
            dot, dot_c = "≈", COLORS["gold"]
        else:
            dot, dot_c = "↓", COLORS["text_dim"]
        self._dot_lbl.configure(text=dot, text_color=dot_c)

        self.grid()   # make visible in its grid cell

    def hide(self):
        """Remove from layout without destroying."""
        self._game    = None
        self._visible = False
        self.grid_remove()   # hides but keeps grid info

    def set_image(self, img):
        """Called after deferred image load."""
        if self._visible and self._game:
            self._img_lbl.configure(image=img, fg_color="transparent")