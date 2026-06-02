import customtkinter as ctk
import threading
import webbrowser
import subprocess
import sys
from typing import Optional
from config import COLORS, PRIORITY_OPTIONS, PRIORITY_COLORS
from data.models import Game
import data.repository as repo
import services.steam_api as steam
import services.steamdb_scraper as steamdb
import services.steamgriddb as sgdb
from ui.widgets import make_ctk_image
from ui.settings_loader import get_settings
import i18n


def open_steam_page(app_id: str, fallback_url: str):
    """
    Try to open the Steam app directly to the store page.
    Falls back to the browser if Steam isn't installed.
    """
    steam_url = f"steam://store/{app_id}"
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", steam_url])
        elif sys.platform == "win32":
            subprocess.Popen(["start", steam_url], shell=True)
        else:
            subprocess.Popen(["xdg-open", steam_url])
    except Exception:
        webbrowser.open(fallback_url)


class GameDetailPanel(ctk.CTkFrame):

    def __init__(self, parent, on_close: callable, on_refresh: callable, **kwargs):
        super().__init__(
            parent,
            fg_color=COLORS["panel"],
            corner_radius=0,
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )
        self.on_close   = on_close
        self.on_refresh = on_refresh
        self._game: Optional[Game] = None
        self._build_shell()

    def _build_shell(self):
        # Fixed top bar
        topbar = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0, height=42)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        self._title_label = ctk.CTkLabel(
            topbar, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text"],
        )
        self._title_label.pack(side="left", padx=12, pady=10)

        ctk.CTkButton(
            topbar, text="✕", width=32, height=32,
            fg_color="transparent", text_color=COLORS["text_dim"],
            hover_color=COLORS["card_hover"], corner_radius=6,
            font=ctk.CTkFont(size=13),
            command=self.on_close,
        ).pack(side="right", padx=6, pady=5)

        # Scrollable content
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=COLORS["panel"], corner_radius=0,
        )
        self._scroll.pack(fill="both", expand=True)

    def load_game(self, game: Game):
        self._game = game
        self._title_label.configure(text=game.name)
        for w in self._scroll.winfo_children():
            w.destroy()
        self._render(game)

    # ─────────────────────────────────────────────────────────────

    def _render(self, game: Game):
        s = self._scroll

        # ── Cover ────────────────────────────────────────────────
        cover = make_ctk_image(game.cover_path, size=(160, 240))
        ctk.CTkLabel(s, image=cover, text="").pack(pady=(12, 0))

        # ── Priority badge ───────────────────────────────────────
        badge_color = PRIORITY_COLORS.get(game.priority, "#666")
        badge_row = ctk.CTkFrame(s, fg_color="transparent")
        badge_row.pack(pady=(8, 0))
        ctk.CTkLabel(
            badge_row, text=game.priority,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=badge_color,
            text_color="#FFFFFF" if game.priority != "S" else "#1a0f00",
            corner_radius=4, width=24, height=24,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            badge_row, text=i18n.t(f"priority.{game.priority}"),
            font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"],
        ).pack(side="left")

        # ── Game name ────────────────────────────────────────────
        ctk.CTkLabel(
            s, text=game.name,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text"], wraplength=250,
        ).pack(pady=(4, 0), padx=12)

        # ── CHECK ON STEAM button ────────────────────────────────
        if game.app_id:
            steam_btn = ctk.CTkButton(
                s,
                text=i18n.t("detail.check_on_steam"),
                command=lambda: open_steam_page(game.app_id, game.steam_url),
                fg_color="#1B2838",
                hover_color="#2a475e",
                text_color=COLORS["blue"],
                border_color=COLORS["blue"],
                border_width=1,
                corner_radius=6,
                font=ctk.CTkFont(size=12, weight="bold"),
                height=32,
                width=200,
            )
            steam_btn.pack(pady=(8, 0))

        # ── "I bought this" button ───────────────────────────────
        import data.purchase_repository as purchases
        already_bought = purchases.get_by_app_id(game.app_id)

        if already_bought:
            bought_frame = ctk.CTkFrame(s, fg_color="#0a1f0a",
                                        corner_radius=8, border_width=1,
                                        border_color="#1a4a1a")
            bought_frame.pack(fill="x", padx=12, pady=(8,0))
            ctk.CTkLabel(
                bought_frame,
                text=f"✓  Purchased {already_bought.edition} Edition",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=COLORS["green"],
            ).pack(side="left", padx=12, pady=8)
            ctk.CTkLabel(
                bought_frame,
                text=f"${already_bought.price_paid:,.2f} {already_bought.currency}  ·  {already_bought.purchased_at}",
                font=ctk.CTkFont(size=10),
                text_color=COLORS["text_dim"],
            ).pack(side="right", padx=12)
        else:
            ctk.CTkButton(
                s,
                text="🛒  I bought this game",
                command=lambda: self._mark_purchased(game),
                fg_color=COLORS["green"],
                text_color="#000",
                hover_color="#86efac",
                corner_radius=6,
                font=ctk.CTkFont(size=12, weight="bold"),
                height=34,
            ).pack(fill="x", padx=12, pady=(8, 0))

        self._divider(s)

        # ── Price ────────────────────────────────────────────────
        self._render_price(s, game)
        self._divider(s)

        # ── Smart recommendation ──────────────────────────────────
        self._render_recommendation(s, game)
        self._divider(s)

        # ── Metadata ─────────────────────────────────────────────
        self._info_row(s, i18n.t("game.genre"),     game.genre or "—")
        self._info_row(s, i18n.t("game.year"),       str(game.release_year) if game.release_year else "—")
        self._info_row(s, i18n.t("game.developer"),  game.developer or "—")
        self._info_row(s, i18n.t("game.publisher"),  game.publisher or "—")

        self._divider(s)

        # ── Edit ─────────────────────────────────────────────────
        self._render_edit(s, game)

        # ── Action buttons ───────────────────────────────────────
        ctk.CTkButton(
            s, text=i18n.t("detail.refresh_prices"),
            command=lambda: self._refresh_prices(game),
            fg_color="transparent",
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_dim"], hover_color=COLORS["card_hover"],
            corner_radius=6, height=30, font=ctk.CTkFont(size=10),
        ).pack(fill="x", padx=12, pady=(6, 3))

        ctk.CTkButton(
            s, text=i18n.t("detail.retry_cover"),
            command=lambda: self._download_cover(game),
            fg_color="transparent",
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_dim"], hover_color=COLORS["card_hover"],
            corner_radius=6, height=30, font=ctk.CTkFont(size=10),
        ).pack(fill="x", padx=12, pady=(0, 3))

        ctk.CTkButton(
            s, text=i18n.t("detail.delete_game"),
            command=lambda: self._delete(game),
            fg_color="transparent",
            border_color="#4a1515", border_width=1,
            text_color=COLORS["red"], hover_color="#2a0a0a",
            corner_radius=6, height=30, font=ctk.CTkFont(size=10),
        ).pack(fill="x", padx=12, pady=(0, 16))

    # ─────────────────────────────────────────────────────────────
    # Price section
    # ─────────────────────────────────────────────────────────────

    def _render_price(self, parent, game: Game):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=12)

        if game.price:
            p = game.price
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x")
            ctk.CTkLabel(
                row, text=f"${p.current:,.0f} {p.currency}",
                font=ctk.CTkFont(size=20, weight="bold"),
                text_color=COLORS["green"] if p.is_on_sale else COLORS["text"],
            ).pack(side="left")
            if p.discount_pct:
                ctk.CTkLabel(
                    row, text=f"-{p.discount_pct}%",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    fg_color=COLORS["green"], text_color="#fff",
                    corner_radius=4, width=44, height=22,
                ).pack(side="left", padx=(6, 0))
            if p.base != p.current:
                ctk.CTkLabel(
                    frame, text=f"{i18n.t('detail.base_price')}: ${p.base:,.0f}",
                    font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"],
                ).pack(anchor="w")
        else:
            ctk.CTkLabel(frame, text="—",
                         font=ctk.CTkFont(size=13), text_color=COLORS["text_dim"]).pack(anchor="w")

        if game.price_history and game.price_history.all_time_low > 0:
            h = game.price_history
            ctk.CTkLabel(
                frame, text=f"{i18n.t('game.price_low')}: ${h.all_time_low:,.0f}",
                font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["blue"],
            ).pack(anchor="w", pady=(4, 0))
            if h.all_time_low_date:
                ctk.CTkLabel(frame, text=h.all_time_low_date,
                             font=ctk.CTkFont(size=9), text_color=COLORS["text_dim"],
                             ).pack(anchor="w")

            if game.price_diff_pct is not None:
                diff      = game.price_diff_pct
                rec       = game.buy_recommendation
                rec_color = COLORS["green"] if diff <= 5 else (COLORS["gold"] if diff <= 25 else COLORS["red"])
                ctk.CTkLabel(frame, text=f"→ {rec}",
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=rec_color).pack(anchor="w", pady=(6, 0))

                prog_val = max(0.0, min(1.0, 1 - diff / 100))
                prog_row = ctk.CTkFrame(frame, fg_color="transparent")
                prog_row.pack(fill="x", pady=(3, 0))
                ctk.CTkLabel(prog_row, text="min", font=ctk.CTkFont(size=8),
                             text_color=COLORS["text_dim"]).pack(side="left")
                prog = ctk.CTkProgressBar(
                    prog_row, fg_color=COLORS["border"],
                    progress_color=COLORS["green"] if prog_val > 0.9 else COLORS["gold"],
                )
                prog.pack(side="left", fill="x", expand=True, padx=4)
                prog.set(prog_val)
                ctk.CTkLabel(prog_row, text="base", font=ctk.CTkFont(size=8),
                             text_color=COLORS["text_dim"]).pack(side="left")

    # ─────────────────────────────────────────────────────────────
    # Smart recommendation
    # ─────────────────────────────────────────────────────────────

    def _render_recommendation(self, parent, game: Game):
        from services.recommendation import get_recommendation

        rec = get_recommendation(game)

        # Color per verdict
        colors = {
            "buy_now":   COLORS["green"],
            "good_deal": COLORS["blue"],
            "wait":      COLORS["gold"],
            "no_data":   COLORS["text_dim"],
        }
        accent = colors.get(rec["verdict"], COLORS["text_dim"])

        icons = {
            "buy_now":   "✓",
            "good_deal": "◎",
            "wait":      "⏳",
            "no_data":   "—",
        }
        icon = icons.get(rec["verdict"], "—")

        # Card
        card = ctk.CTkFrame(
            parent,
            fg_color=COLORS["card"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.pack(fill="x", padx=12, pady=(0, 4))

        # Accent bar
        ctk.CTkFrame(card, fg_color=accent, width=3, corner_radius=0).place(
            x=0, y=0, relheight=1,
        )

        # Header row: icon + headline
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=(14, 10), pady=(10, 4))

        ctk.CTkLabel(
            header, text=icon,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=accent,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            header, text=rec["headline"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=accent, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # Reason text
        if rec["reason"]:
            ctk.CTkLabel(
                card, text=rec["reason"],
                font=ctk.CTkFont(size=10),
                text_color=COLORS["text_dim"],
                wraplength=270, justify="left", anchor="w",
            ).pack(anchor="w", padx=14, pady=(0, 8))

        # Next sale box
        if rec["next_sale"]:
            sale_box = ctk.CTkFrame(
                card, fg_color=COLORS["bg"],
                corner_radius=6, border_width=1,
                border_color=COLORS["border"],
            )
            sale_box.pack(fill="x", padx=10, pady=(0, 10))

            ctk.CTkLabel(
                sale_box,
                text="NEXT LIKELY SALE",
                font=ctk.CTkFont(size=9),
                text_color=COLORS["text_dim"],
            ).pack(anchor="w", padx=10, pady=(6, 0))

            ctk.CTkLabel(
                sale_box,
                text=rec["next_sale"],
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=COLORS["text"],
            ).pack(anchor="w", padx=10, pady=(1, 0))

            # Estimated price row
            if rec["est_price"] and game.price:
                est_row = ctk.CTkFrame(sale_box, fg_color="transparent")
                est_row.pack(fill="x", padx=10, pady=(4, 8))

                ctk.CTkLabel(
                    est_row,
                    text=f"Est. price: ",
                    font=ctk.CTkFont(size=10),
                    text_color=COLORS["text_dim"],
                ).pack(side="left")

                ctk.CTkLabel(
                    est_row,
                    text=f"${rec['est_price']:,.0f} {game.price.currency}",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=COLORS["green"],
                ).pack(side="left")

                if rec["est_discount"]:
                    ctk.CTkLabel(
                        est_row,
                        text=f"  (-{rec['est_discount']}%)",
                        font=ctk.CTkFont(size=10),
                        text_color=COLORS["text_dim"],
                    ).pack(side="left")

                # Confidence badge
                conf_colors = {"high": COLORS["green"], "medium": COLORS["gold"], "low": COLORS["text_dim"]}
                ctk.CTkLabel(
                    est_row,
                    text=rec["confidence"].upper(),
                    font=ctk.CTkFont(size=8),
                    fg_color=conf_colors.get(rec["confidence"], COLORS["border"]),
                    text_color="#000" if rec["confidence"] == "high" else COLORS["text"],
                    corner_radius=4,
                ).pack(side="right", padx=(4, 0))

    # ─────────────────────────────────────────────────────────────
    # Edit section
    # ─────────────────────────────────────────────────────────────

    def _render_edit(self, parent, game: Game):
        ctk.CTkLabel(parent, text=i18n.t("detail.edit_section"),
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLORS["text"]).pack(anchor="w", padx=12, pady=(0, 6))

        ctk.CTkLabel(parent, text=i18n.t("game.priority"),
                     font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"],
                     ).pack(anchor="w", padx=12)

        p_row = ctk.CTkFrame(parent, fg_color="transparent")
        p_row.pack(anchor="w", padx=12, pady=(3, 8))
        for p in PRIORITY_OPTIONS:
            color = PRIORITY_COLORS.get(p, "#666")
            btn = ctk.CTkButton(
                p_row, text=p, width=36, height=28,
                fg_color=color if game.priority == p else "transparent",
                text_color="#fff", hover_color=color,
                border_color=color, border_width=1, corner_radius=5,
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda pv=p: self._update_priority(game, pv),
            )
            btn.pack(side="left", padx=(0, 3))
            self.__dict__[f"_det_pb_{p}"] = btn

        ctk.CTkLabel(parent, text=i18n.t("game.notes"),
                     font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"],
                     ).pack(anchor="w", padx=12)
        self._notes_box = ctk.CTkTextbox(
            parent, height=60,
            fg_color=COLORS["card"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text"],
        )
        self._notes_box.pack(fill="x", padx=12, pady=(3, 0))
        if game.notes:
            self._notes_box.insert("1.0", game.notes)

        ctk.CTkButton(
            parent, text=i18n.t("actions.save"),
            command=lambda: self._save_edits(game),
            fg_color=COLORS["blue"], text_color="#0a1929",
            hover_color="#4fa8d8", corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"), height=30,
        ).pack(fill="x", padx=12, pady=(6, 0))

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────

    def _divider(self, parent):
        ctk.CTkFrame(parent, fg_color=COLORS["border"], height=1, corner_radius=0).pack(
            fill="x", padx=12, pady=10,
        )

    def _info_row(self, parent, label: str, value: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=1)
        ctk.CTkLabel(row, text=label + ":", width=100,
                     font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"],
                     anchor="w").pack(side="left")
        ctk.CTkLabel(row, text=value,
                     font=ctk.CTkFont(size=10), text_color=COLORS["text"],
                     anchor="w", wraplength=150, justify="left").pack(side="left")

    # ─────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────

    def _update_priority(self, game: Game, p: str):
        game.priority = p
        repo.update(game)
        for pr in PRIORITY_OPTIONS:
            color = PRIORITY_COLORS.get(pr, "#666")
            btn = self.__dict__.get(f"_det_pb_{pr}")
            if btn:
                btn.configure(fg_color=color if pr == p else "transparent")
        self.on_refresh()

    def _save_edits(self, game: Game):
        game.notes = self._notes_box.get("1.0", "end").strip()
        repo.update(game)
        self.on_refresh()

    def _refresh_prices(self, game: Game):
        def _work():
            settings = get_settings()
            data = steam.get_app_details(game.app_id, country=settings.get("country", "mx"))
            if data:
                game.price = steam.parse_price(data)
            history = steamdb.get_price_history(game.app_id)
            if history:
                game.price_history = history
            repo.update(game)
            self.after(0, lambda: self.load_game(game))
            self.after(0, self.on_refresh)
        threading.Thread(target=_work, daemon=True).start()

    def _download_cover(self, game: Game):
        def _work():
            settings = get_settings()
            api_key  = settings.get("steamgriddb_key", "")
            cover = sgdb.download_cover(game.app_id, api_key, game.name)
            if cover:
                game.cover_path = cover
                repo.update(game)
                self.after(0, lambda: self.load_game(game))
                self.after(0, self.on_refresh)
        threading.Thread(target=_work, daemon=True).start()

    def _mark_purchased(self, game: Game):
        from ui.mark_purchased_dialog import MarkPurchasedDialog

        def _on_success(purchase):
            self.on_refresh()
            self.load_game(game)   # reload panel to show "purchased" state

        MarkPurchasedDialog(self, game=game, on_success=_on_success)

    def _check_steam_library(self, game: Game) -> bool:
        """
        Check if game is in user's Steam library.
        Returns True if found — triggers auto-mark as purchased.
        """
        from ui.settings_loader import get_settings
        import requests
        settings = get_settings()
        steam_id = settings.get("steam_id64", "")
        api_key  = settings.get("steam_api_key", "")
        if not steam_id or not api_key:
            return False
        try:
            resp = requests.get(
                "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/",
                params={"key": api_key, "steamid": steam_id,
                        "include_appinfo": False, "format": "json"},
                timeout=8,
            )
            owned = resp.json().get("response", {}).get("games", [])
            return any(str(g["appid"]) == game.app_id for g in owned)
        except Exception:
            return False

    def _delete(self, game: Game):
        repo.delete(game.id)
        self.on_close()
        self.on_refresh()