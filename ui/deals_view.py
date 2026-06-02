import customtkinter as ctk
import threading
from datetime import datetime, date
from pathlib import Path
from PIL import Image
from config import COLORS, STEAM_SALE_EVENTS
import data.repository as repo
import services.steam_api as steam
import i18n
from ui.settings_loader import get_settings

BAND_W = 560
BAND_H = 70


class DealsView(ctk.CTkFrame):

    def __init__(self, parent, on_game_click: callable, **kwargs):
        super().__init__(parent, fg_color=COLORS["bg"], **kwargs)
        self.on_game_click = on_game_click
        self._refreshing   = False
        self._img_refs     = []
        self._build()

    # ─────────────────────────────────────────────────────────────
    # Shell
    # ─────────────────────────────────────────────────────────────

    def _build(self):
        header = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text=i18n.t("deals.title"),
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["text"],
        ).pack(side="left", padx=18, pady=14)

        self._refresh_btn = ctk.CTkButton(
            header, text=i18n.t("deals.refresh_all"),
            command=self._refresh_all_prices,
            fg_color="transparent",
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_dim"],
            hover_color=COLORS["card_hover"],
            corner_radius=6, height=32, width=210,
            font=ctk.CTkFont(size=11),
        )
        self._refresh_btn.pack(side="right", padx=18)

        self._status_lbl = ctk.CTkLabel(
            header, text="",
            font=ctk.CTkFont(size=11), text_color=COLORS["green"],
        )
        self._status_lbl.pack(side="right", padx=(0, 8))

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=COLORS["bg"], corner_radius=0,
        )
        self._scroll.pack(fill="both", expand=True)
        self.refresh()

    # ─────────────────────────────────────────────────────────────
    # Refresh
    # ─────────────────────────────────────────────────────────────

    def refresh(self):
        self._img_refs.clear()
        for w in self._scroll.winfo_children():
            w.destroy()
        # Pre-generate all banner images (fast, cached after first run)
        threading.Thread(target=self._pregenerate_banners, daemon=True).start()
        self._render_sale_cards()
        self._render_on_sale()

    def _pregenerate_banners(self):
        """Generate all banner images in background so they're ready."""
        from services.sale_images import get_banner_path
        today = date.today()
        events = [e for e in STEAM_SALE_EVENTS
                  if datetime.strptime(e["end"], "%Y-%m-%d").date() >= today]
        for event in events:
            try:
                get_banner_path(event["key"], event["color_top"],
                                event["color_bot"], event["emoji"])
            except Exception:
                pass
        # Now apply images on main thread
        self.after(100, self._apply_all_banners)

    def _apply_all_banners(self):
        """After generation, apply images to all visible cards."""
        from services.sale_images import get_banner_path
        today = date.today()
        events = [e for e in STEAM_SALE_EVENTS
                  if datetime.strptime(e["end"], "%Y-%m-%d").date() >= today]
        for event in events:
            try:
                path = get_banner_path(event["key"], event["color_top"],
                                       event["color_bot"], event["emoji"])
                self._apply_banner_to_card(event, path)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────
    # Sale calendar cards
    # ─────────────────────────────────────────────────────────────

    def _render_sale_cards(self):
        ctk.CTkLabel(
            self._scroll, text=i18n.t("deals.upcoming"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text_dim"],
        ).pack(anchor="w", padx=16, pady=(14, 8))

        today  = date.today()
        events = sorted(
            [e for e in STEAM_SALE_EVENTS
             if datetime.strptime(e["end"], "%Y-%m-%d").date() >= today],
            key=lambda e: e["start"],
        )

        grid = ctk.CTkFrame(self._scroll, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(0, 16))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        for idx, event in enumerate(events):
            card = self._make_sale_card(grid, event, today)
            card.grid(
                row=idx // 2, column=idx % 2,
                padx=(0, 10) if idx % 2 == 0 else 0,
                pady=(0, 12), sticky="ew",
            )

    def _make_sale_card(self, parent, event: dict, today: date) -> ctk.CTkFrame:
        start = datetime.strptime(event["start"], "%Y-%m-%d").date()
        end   = datetime.strptime(event["end"],   "%Y-%m-%d").date()

        is_active     = start <= today <= end
        days_to_start = (start - today).days if start > today else 0
        days_left     = (end   - today).days if is_active    else 0

        name      = i18n.t(f"sale_events.{event['key']}")
        top_color = event["color_top"]
        emoji     = event["emoji"]
        confirmed = event["confirmed"]

        card = ctk.CTkFrame(
            parent,
            fg_color=COLORS["card"],
            corner_radius=12,
            border_width=2,
            border_color=top_color if is_active else COLORS["border"],
        )
        card._event_key = event["key"]
        card._event     = event

        # ── Banner (full-width image area) ───────────────────────
        banner = ctk.CTkFrame(
            card,
            fg_color=top_color,      # solid fallback color
            corner_radius=0,
            height=BAND_H,
        )
        banner.pack(fill="x")
        banner.pack_propagate(False)
        card._banner = banner

        # Text overlay (always on top of whatever background)
        self._render_banner_text(banner, emoji, name, is_active, confirmed, top_color)

        # ── Info strip ───────────────────────────────────────────
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(fill="x", padx=14, pady=(8, 10))

        ctk.CTkLabel(
            info,
            text=f"  {event['start']}  →  {event['end']}",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"], anchor="w",
        ).pack(side="left")

        status_text  = (i18n.t("deals.days_left",  n=days_left)  if is_active
                        else i18n.t("deals.starts_in", n=days_to_start))
        status_color = COLORS["green"] if is_active else COLORS["text"]

        ctk.CTkLabel(
            info, text=status_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=status_color,
        ).pack(side="right")

        return card

    def _render_banner_text(self, banner, emoji, name, is_active, confirmed, color):
        """Render emoji + title + badge on banner. Called for placeholder and image overlay."""
        for w in banner.winfo_children():
            w.destroy()

        row = ctk.CTkFrame(banner, fg_color="transparent")
        row.place(x=0, y=0, relwidth=1, relheight=1)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=14, pady=8)

        # Title row
        title_row = ctk.CTkFrame(left, fg_color="transparent")
        title_row.pack(anchor="w")

        ctk.CTkLabel(
            title_row, text=emoji,
            font=ctk.CTkFont(size=22),
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            title_row, text=name,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#FFFFFF",
        ).pack(side="left")

        # Badge row
        badge_text  = (i18n.t("deals.active_now") if is_active
                       else i18n.t("deals.confirmed")  if confirmed
                       else i18n.t("deals.estimated"))
        badge_color = COLORS["green"] if is_active else COLORS["border"]
        badge_fg    = "#FFFFFF"

        ctk.CTkLabel(
            left, text=badge_text,
            font=ctk.CTkFont(size=9),
            fg_color=badge_color, text_color=badge_fg,
            corner_radius=4,
        ).pack(anchor="w", pady=(2, 0))

    # ─────────────────────────────────────────────────────────────
    # Apply generated image to card banner
    # ─────────────────────────────────────────────────────────────

    def _apply_banner_to_card(self, event: dict, image_path: str):
        """Find the card for this event and overlay its banner with the image."""
        if not Path(image_path).exists():
            return

        def _find_cards(container):
            for child in container.winfo_children():
                if hasattr(child, "_event_key") and child._event_key == event["key"]:
                    self._set_banner_image(child, image_path, event)
                    return
                _find_cards(child)

        try:
            _find_cards(self._scroll)
        except Exception:
            pass

    def _set_banner_image(self, card, image_path: str, event: dict):
        """Overlay the banner frame with the generated image + text on top."""
        try:
            banner = card._banner

            # Load generated image
            img = Image.open(image_path).convert("RGB")
            # Scale to fill banner exactly
            img = img.resize((BAND_W, BAND_H), Image.LANCZOS)

            ctk_img = ctk.CTkImage(
                light_image=img, dark_image=img,
                size=(BAND_W, BAND_H),
            )
            self._img_refs.append(ctk_img)

            # Clear banner and set image as background
            for w in banner.winfo_children():
                w.destroy()

            img_lbl = ctk.CTkLabel(banner, image=ctk_img, text="")
            img_lbl.place(x=0, y=0, relwidth=1, relheight=1)

            # Re-render text on top of image
            is_active = (
                datetime.strptime(event["start"], "%Y-%m-%d").date()
                <= date.today()
                <= datetime.strptime(event["end"], "%Y-%m-%d").date()
            )
            name = i18n.t(f"sale_events.{event['key']}")

            self._render_banner_text(
                banner,
                event["emoji"], name,
                is_active, event["confirmed"],
                event["color_top"],
            )

        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────
    # On-sale wishlist games
    # ─────────────────────────────────────────────────────────────

    def _render_on_sale(self):
        games = repo.get_on_sale()
        currency = next((g.price.currency for g in games if g.price), "")

        header_row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        header_row.pack(fill="x", padx=16, pady=(4, 6))

        ctk.CTkLabel(
            header_row, text=i18n.t("deals.on_sale"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text_dim"],
        ).pack(side="left")

        if currency:
            ctk.CTkLabel(
                header_row,
                text=i18n.t("deals.currency_note", currency=currency),
                font=ctk.CTkFont(size=10),
                text_color=COLORS["text_dim"],
            ).pack(side="right")

        if not games:
            ctk.CTkLabel(
                self._scroll,
                text=i18n.t("deals.no_deals"),
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_dim"],
            ).pack(anchor="w", padx=20, pady=(0, 20))
            return

        for game in sorted(games, key=lambda g: g.price_diff_pct or 999):
            self._game_row(game)

    def _game_row(self, game):
        from config import PRIORITY_COLORS
        row = ctk.CTkFrame(
            self._scroll, fg_color=COLORS["card"],
            corner_radius=8, border_width=1, border_color=COLORS["border"],
        )
        row.pack(fill="x", padx=16, pady=3)
        row.bind("<Button-1>", lambda e: self.on_game_click(game))

        badge_color = PRIORITY_COLORS.get(game.priority, "#666")
        ctk.CTkLabel(
            row, text=game.priority,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=badge_color,
            text_color="#FFFFFF" if game.priority != "S" else "#1a0f00",
            corner_radius=4, width=26, height=26,
        ).pack(side="left", padx=12, pady=10)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info, text=game.name,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            info,
            text=f"{game.genre.split(',')[0] if game.genre else '—'} · {game.release_year or '—'}",
            font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"], anchor="w",
        ).pack(anchor="w")

        if game.price:
            prices = ctk.CTkFrame(row, fg_color="transparent")
            prices.pack(side="right", padx=14)
            if game.price.discount_pct:
                ctk.CTkLabel(
                    prices, text=f"-{game.price.discount_pct}%",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    fg_color=COLORS["green"], text_color="#FFFFFF",
                    corner_radius=4, width=50, height=24,
                ).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                prices, text=f"${game.price.base:,.0f}",
                font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"],
            ).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(
                prices,
                text=f"${game.price.current:,.0f} {game.price.currency}",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=COLORS["green"],
            ).pack(side="left")

    # ─────────────────────────────────────────────────────────────
    # Refresh all prices
    # ─────────────────────────────────────────────────────────────

    def _refresh_all_prices(self):
        if self._refreshing:
            return
        self._refreshing = True
        self._refresh_btn.configure(state="disabled")

        def _work():
            settings = get_settings()
            country  = settings.get("country", "mx")
            games    = repo.get_all()
            total    = len(games)
            for i, game in enumerate(games):
                self.after(0, lambda i=i: self._status_lbl.configure(
                    text=i18n.t("settings.refreshing", n=f"{i+1}/{total}"),
                    text_color=COLORS["blue"],
                ))
                new_price = steam.refresh_price(game.app_id, country=country)
                if new_price:
                    game.price = new_price
                    repo.update(game)
            self.after(0, self._on_refresh_done, total)

        threading.Thread(target=_work, daemon=True).start()

    def _on_refresh_done(self, total: int):
        self._refreshing = False
        self._refresh_btn.configure(state="normal")
        self._status_lbl.configure(
            text=i18n.t("settings.refresh_done", n=total),
            text_color=COLORS["green"],
        )
        self.after(4000, lambda: self._status_lbl.configure(text=""))
        self.refresh()