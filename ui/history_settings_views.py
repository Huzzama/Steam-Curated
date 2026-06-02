import customtkinter as ctk
import json
from pathlib import Path
from config import COLORS, LOCALES, BASE_DIR
import data.repository as repo
import i18n

_SETTINGS_PATH = BASE_DIR / "settings.json"


def load_settings() -> dict:
    if _SETTINGS_PATH.exists():
        with open(_SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "locale":             "es",
        "steamgriddb_key":    "",
        "country":            "mx",
        "steam_api_key":      "",
        "steam_id64":         "",
        "steam_name":         "",
        "pimpmysteam_token":  "",   # JWT from pimpmysteam.com login
        "api_url":            "https://steamkustom-production.up.railway.app",
    }


def save_settings(settings: dict) -> None:
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


# ── History View ──────────────────────────────────────────────────────────────

MAX_HISTORY_ROWS = 60   # pre-built row pool size

class HistoryView(ctk.CTkFrame):

    def __init__(self, parent, on_game_click: callable, **kwargs):
        super().__init__(parent, fg_color=COLORS["bg"], **kwargs)
        self.on_game_click  = on_game_click
        self._last_ids: list = []
        self._built          = False
        self._build()

    def _build(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=COLORS["panel"],
                              corner_radius=0, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text=i18n.t("history.title"),
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=COLORS["text"]).pack(side="left", padx=18, pady=14)
        ctk.CTkLabel(header, text=i18n.t("history.subtitle"),
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_dim"]).pack(side="left")

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=COLORS["bg"], corner_radius=0)
        self._scroll.pack(fill="both", expand=True)

        # Empty label (hidden until needed)
        self._empty_lbl = ctk.CTkLabel(
            self._scroll, text=i18n.t("history.empty"),
            font=ctk.CTkFont(size=13), text_color=COLORS["text_dim"])

        # Pre-build pool of month labels + row widgets
        # Each row: (outer_frame, badge_lbl, name_lbl, meta_lbl, date_lbl)
        self._month_labels: list[ctk.CTkLabel] = []
        self._row_pool: list[tuple] = []

        # Month labels (max 12 months visible at once)
        for _ in range(12):
            lbl = ctk.CTkLabel(self._scroll, text="",
                               font=ctk.CTkFont(size=12, weight="bold"),
                               text_color=COLORS["blue"])
            self._month_labels.append(lbl)

        # Row pool
        for _ in range(MAX_HISTORY_ROWS):
            row = ctk.CTkFrame(self._scroll, fg_color=COLORS["card"],
                               corner_radius=8, border_width=1,
                               border_color=COLORS["border"])

            badge = ctk.CTkLabel(row, text="",
                                 font=ctk.CTkFont(size=10, weight="bold"),
                                 fg_color=COLORS["border"], text_color="#fff",
                                 corner_radius=4, width=22, height=22)
            badge.pack(side="left", padx=12, pady=10)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True)

            name_lbl = ctk.CTkLabel(info, text="",
                                    font=ctk.CTkFont(size=13, weight="bold"),
                                    text_color=COLORS["text"], anchor="w")
            name_lbl.pack(anchor="w")

            meta_lbl = ctk.CTkLabel(info, text="",
                                    font=ctk.CTkFont(size=11),
                                    text_color=COLORS["text_dim"], anchor="w")
            meta_lbl.pack(anchor="w")

            date_lbl = ctk.CTkLabel(row, text="",
                                    font=ctk.CTkFont(size=11),
                                    text_color=COLORS["text_dim"])
            date_lbl.pack(side="right", padx=14)

            self._row_pool.append((row, badge, name_lbl, meta_lbl, date_lbl))

        self._built = True
        self.refresh()

    def refresh(self):
        if not self._built:
            return
        games  = repo.get_recent(limit=50)
        new_ids = [g.id for g in games]
        if new_ids == self._last_ids:
            return
        self._last_ids = new_ids
        self._layout(games)

    def _layout(self, games):
        from collections import defaultdict
        from config import PRIORITY_COLORS

        # Hide everything first (O(n) configure calls, no destroy)
        self._empty_lbl.pack_forget()
        for lbl in self._month_labels:
            lbl.pack_forget()
        for row, *_ in self._row_pool:
            row.pack_forget()

        if not games:
            self._empty_lbl.pack(pady=60)
            return

        # Group by month
        by_month: dict[str, list] = defaultdict(list)
        for g in games:
            by_month[g.date_added[:7] if g.date_added else "—"].append(g)

        month_idx = 0
        row_idx   = 0

        for month_key in sorted(by_month.keys(), reverse=True):
            if month_idx >= len(self._month_labels):
                break

            # Month label
            try:
                year, month = month_key.split("-")
                label = f"{i18n.t(f'months.{int(month)}')} {year}"
            except Exception:
                label = month_key

            m_lbl = self._month_labels[month_idx]
            m_lbl.configure(text=label)
            m_lbl.pack(anchor="w", padx=16, pady=(14,4))
            month_idx += 1

            # Rows for this month
            for game in by_month[month_key]:
                if row_idx >= len(self._row_pool):
                    break

                row, badge, name_lbl, meta_lbl, date_lbl = self._row_pool[row_idx]

                # Update data in-place
                badge_color = PRIORITY_COLORS.get(game.priority, COLORS["border"])
                badge.configure(
                    text=game.priority, fg_color=badge_color,
                    text_color="#1a0f00" if game.priority == "S" else "#fff",
                )
                name_lbl.configure(text=game.name)
                meta_lbl.configure(
                    text=f"{game.genre.split(',')[0] if game.genre else '—'} · {game.developer or '—'}"
                )
                date_lbl.configure(
                    text=i18n.t("history.added_on", date=game.date_added)
                )

                # Re-bind click to current game
                for w in (row, badge, name_lbl, meta_lbl, date_lbl):
                    w.bind("<Button-1>",
                           lambda e, g=game: self.on_game_click(g))

                row.pack(fill="x", padx=16, pady=2)
                row_idx += 1


# ── Settings View ─────────────────────────────────────────────────────────────

class SettingsView(ctk.CTkFrame):

    def __init__(self, parent, on_locale_change: callable, **kwargs):
        super().__init__(parent, fg_color=COLORS["bg"], **kwargs)
        self.on_locale_change = on_locale_change
        self._settings = load_settings()
        self._key_visible = False
        self._build()

    def _build(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text=i18n.t("settings.title"),
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["text"],
        ).pack(side="left", padx=18, pady=14)

        content = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        content.pack(fill="both", expand=True, padx=40, pady=20)

        # ── Language ─────────────────────────────────────────────
        self._section(content, i18n.t("settings.language"))
        ctk.CTkLabel(
            content, text=i18n.t("settings.language_desc"),
            font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"],
        ).pack(anchor="w", pady=(0, 8))

        locale_options = [f"{code} — {name}" for code, name in LOCALES.items()]
        current_locale = self._settings.get("locale", "es")
        current_display = next(
            (f"{k} — {v}" for k, v in LOCALES.items() if k == current_locale),
            locale_options[0],
        )
        self._locale_var = ctk.StringVar(value=current_display)
        ctk.CTkOptionMenu(
            content,
            values=locale_options,
            variable=self._locale_var,
            fg_color=COLORS["card"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            dropdown_fg_color=COLORS["panel"],
            dropdown_hover_color=COLORS["card_hover"],
            dropdown_text_color=COLORS["text"],
            width=280, height=36,
        ).pack(anchor="w")

        # ── SteamGridDB API Key ───────────────────────────────────
        self._section(content, i18n.t("settings.api_key"))
        ctk.CTkLabel(
            content, text=i18n.t("settings.api_key_desc"),
            font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"],
        ).pack(anchor="w", pady=(0, 8))

        key_row = ctk.CTkFrame(content, fg_color="transparent")
        key_row.pack(anchor="w", fill="x")

        current_key = self._settings.get("steamgriddb_key", "")
        self._api_key_var = ctk.StringVar(value=current_key)
        self._key_entry = ctk.CTkEntry(
            key_row,
            textvariable=self._api_key_var,
            placeholder_text="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            show="•",
            width=300, height=36,
            fg_color=COLORS["card"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
        )
        self._key_entry.pack(side="left")

        # Show/hide toggle
        self._eye_btn = ctk.CTkButton(
            key_row,
            text=i18n.t("settings.show_key"),
            width=90, height=36,
            fg_color="transparent",
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_dim"],
            hover_color=COLORS["card_hover"],
            corner_radius=6,
            font=ctk.CTkFont(size=11),
            command=self._toggle_key_visibility,
        )
        self._eye_btn.pack(side="left", padx=(8, 0))

        # Key status indicator
        self._key_status = ctk.CTkLabel(
            content,
            text=i18n.t("settings.key_saved") if current_key else i18n.t("settings.key_missing"),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["green"] if current_key else COLORS["gold"],
        )
        self._key_status.pack(anchor="w", pady=(6, 0))

        # ── Country / Currency ────────────────────────────────────
        self._section(content, i18n.t("settings.currency_section"))
        ctk.CTkLabel(
            content, text=i18n.t("settings.currency_desc"),
            font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"],
        ).pack(anchor="w", pady=(0, 8))

        countries = [
            "mx — MXN (México)",
            "us — USD (Estados Unidos)",
            "ar — ARS (Argentina)",
            "br — BRL (Brasil)",
            "es — EUR (España)",
            "jp — JPY (Japón)",
        ]
        current_country = self._settings.get("country", "mx")
        current_country_display = next(
            (c for c in countries if c.startswith(current_country)),
            countries[0],
        )
        self._country_var = ctk.StringVar(value=current_country_display)
        ctk.CTkOptionMenu(
            content, values=countries,
            variable=self._country_var,
            fg_color=COLORS["card"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            dropdown_fg_color=COLORS["panel"],
            dropdown_hover_color=COLORS["card_hover"],
            dropdown_text_color=COLORS["text"],
            width=280, height=36,
        ).pack(anchor="w")

        # ── PimpMySteam Account ──────────────────────────────────
        self._section(content, "PimpMySteam Account")

        ctk.CTkLabel(
            content,
            text="Generate a token at pimpmysteam.com → Settings → Apps. "
                 "Paste it here to enable Drive sync and Steam wishlist import.",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
            wraplength=440, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        token_row = ctk.CTkFrame(content, fg_color="transparent")
        token_row.pack(fill="x", pady=(0, 4))

        current_token = self._settings.get("pimpmysteam_token", "")
        self._sk_token_var = ctk.StringVar(value=current_token)
        self._sk_token_entry = ctk.CTkEntry(
            token_row,
            textvariable=self._sk_token_var,
            placeholder_text="Paste your app token here…",
            show="•" if current_token else "",
            fg_color=COLORS["card"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            width=340, height=34,
        )
        self._sk_token_entry.pack(side="left", padx=(0, 8))

        self._sk_status_lbl = ctk.CTkLabel(
            token_row, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
        )
        self._sk_status_lbl.pack(side="left")

        ctk.CTkButton(
            content,
            text="Verify Token",
            command=self._verify_sk_token,
            fg_color="transparent",
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_dim"],
            hover_color=COLORS["card_hover"],
            corner_radius=6, height=30, width=120,
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(0, 4))

        ctk.CTkLabel(
            content,
            text="pimpmysteam.com → Settings → Apps → Generate Token",
            font=ctk.CTkFont(size=9),
            text_color=COLORS["text_dim"],
        ).pack(anchor="w", pady=(0, 8))

        # ── Steam Account ─────────────────────────────────────────
        SteamConnectPanel(content).pack(fill="x")

        # ── Google Drive Sync ─────────────────────────────────────
        SyncPanel(content).pack(fill="x")

        # ── Save ──────────────────────────────────────────────────
        ctk.CTkButton(
            content,
            text=i18n.t("settings.save_settings"),
            command=self._save,
            fg_color=COLORS["blue"],
            text_color="#0a1929",
            hover_color="#4fa8d8",
            corner_radius=6,
            font=ctk.CTkFont(size=13, weight="bold"),
            width=180, height=38,
        ).pack(anchor="w", pady=(28, 0))

        self._feedback = ctk.CTkLabel(
            content, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["green"],
        )
        self._feedback.pack(anchor="w", pady=(6, 0))

    # ── Helpers ───────────────────────────────────────────────────

    def _verify_sk_token(self):
        """Verify the PimpMySteam token and save if valid."""
        token = self._sk_token_var.get().strip()
        if not token:
            self._sk_status_lbl.configure(
                text="Enter a token first", text_color=COLORS["gold"])
            return

        self._sk_status_lbl.configure(text="Verifying…", text_color=COLORS["blue"])

        import threading
        def _check():
            from services.pimpmysteam_auth import verify_token
            user = verify_token(token)
            def _update():
                if user:
                    from ui.settings_loader import load_settings, save_settings
                    s = load_settings()
                    s["pimpmysteam_token"] = token
                    save_settings(s)
                    self._settings["pimpmysteam_token"] = token
                    self._sk_token_entry.configure(show="•")
                    self._sk_status_lbl.configure(
                        text=f"✓ {user.get('username', 'Connected')}",
                        text_color=COLORS["green"],
                    )
                else:
                    self._sk_status_lbl.configure(
                        text="✗ Invalid token",
                        text_color=COLORS["red"],
                    )
            self.after(0, _update)

        threading.Thread(target=_check, daemon=True).start()

    def _section(self, parent, title: str):
        ctk.CTkLabel(
            parent, text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", pady=(24, 4))
        ctk.CTkFrame(
            parent, fg_color=COLORS["border"], height=1, corner_radius=0,
        ).pack(fill="x", pady=(0, 12))

    def _toggle_key_visibility(self):
        self._key_visible = not self._key_visible
        self._key_entry.configure(show="" if self._key_visible else "•")
        self._eye_btn.configure(text=i18n.t("settings.hide_key") if self._key_visible else i18n.t("settings.show_key"))

    def _save(self):
        locale_str  = self._locale_var.get().split(" — ")[0]
        country_str = self._country_var.get().split(" — ")[0]
        api_key     = self._api_key_var.get().strip()

        old_country    = self._settings.get("country", "mx")
        country_changed = country_str != old_country

        settings = {
            "locale":          locale_str,
            "steamgriddb_key": api_key,
            "country":         country_str,
        }
        save_settings(settings)
        self._settings = settings

        if hasattr(self, "_key_status"):
            self._key_status.configure(
                text=i18n.t("settings.key_saved") if api_key else i18n.t("settings.key_missing"),
                text_color=COLORS["green"] if api_key else COLORS["gold"],
            )

        locale_changed = locale_str != i18n.current_locale()

        # Handle currency refresh first (before any UI rebuild)
        if country_changed:
            import threading
            import services.steam_api as steam
            import data.repository as repo_mod

            def _refresh_prices(then_rebuild=False):
                games = repo_mod.get_all()
                total = len(games)
                for idx, game in enumerate(games):
                    new_price = steam.refresh_price(game.app_id, country=country_str)
                    if new_price:
                        game.price = new_price
                        repo_mod.update(game)
                    # Only update feedback if UI still exists
                    try:
                        self.after(0, lambda i=idx: self._feedback.configure(
                            text=i18n.t("settings.refreshing", n=f"{i+1}/{total}"),
                            text_color=COLORS["blue"],
                        ))
                    except Exception:
                        pass
                if then_rebuild:
                    # Now safe to rebuild UI after prices are done
                    self.after(0, self.on_locale_change)
                else:
                    try:
                        self.after(0, lambda: self._feedback.configure(
                            text=i18n.t("settings.refresh_done", n=total),
                            text_color=COLORS["green"],
                        ))
                        self.after(4000, lambda: self._feedback.configure(text=""))
                    except Exception:
                        pass

            if locale_changed:
                # Refresh prices first, THEN rebuild UI for new locale
                i18n.load_locale(locale_str)
                self._feedback.configure(
                    text=i18n.t("settings.refreshing", n="..."),
                    text_color=COLORS["blue"],
                )
                threading.Thread(
                    target=lambda: _refresh_prices(then_rebuild=True),
                    daemon=True,
                ).start()
            else:
                # Only currency changed
                self._feedback.configure(
                    text=i18n.t("settings.refreshing", n="..."),
                    text_color=COLORS["blue"],
                )
                threading.Thread(
                    target=lambda: _refresh_prices(then_rebuild=False),
                    daemon=True,
                ).start()

        elif locale_changed:
            # Only locale changed — no price refresh needed
            i18n.load_locale(locale_str)
            self.on_locale_change()

        else:
            self._feedback.configure(text=i18n.t("settings.saved"))
            self.after(3000, lambda: self._feedback.configure(text=""))



# ── Sync Panel (injected into SettingsView) ───────────────────────────────────

class SyncPanel(ctk.CTkFrame):
    """
    Google Drive sync section — can be embedded in SettingsView
    or used as a standalone panel.
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._build()

    def _build(self):
        # Section header
        ctk.CTkLabel(
            self, text=i18n.t("sync.title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", pady=(24, 4))
        ctk.CTkFrame(self, fg_color=COLORS["border"], height=1, corner_radius=0).pack(
            fill="x", pady=(0, 12)
        )

        # Description
        ctk.CTkLabel(
            self, text=i18n.t("sync.desc"),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
            wraplength=420, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # Privacy note
        ctk.CTkLabel(
            self, text=i18n.t("sync.privacy_note"),
            font=ctk.CTkFont(size=10),
            text_color=COLORS["blue"],
            wraplength=420, justify="left",
        ).pack(anchor="w", pady=(0, 12))

        # Status indicator
        self._status_lbl = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_dim"],
        )
        self._status_lbl.pack(anchor="w", pady=(0, 10))

        # Buttons row
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(anchor="w")

        self._connect_btn = ctk.CTkButton(
            btn_row,
            text=i18n.t("sync.btn_connect"),
            command=self._connect,
            fg_color=COLORS["blue"], text_color="#0a1929",
            hover_color="#4fa8d8", corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34, width=180,
        )
        self._connect_btn.pack(side="left", padx=(0, 8))

        self._upload_btn = ctk.CTkButton(
            btn_row,
            text=i18n.t("sync.btn_upload"),
            command=self._upload,
            fg_color="transparent",
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_dim"],
            hover_color=COLORS["card_hover"],
            corner_radius=6, height=34, width=160,
            font=ctk.CTkFont(size=11),
            state="disabled",
        )
        self._upload_btn.pack(side="left", padx=(0, 8))

        self._download_btn = ctk.CTkButton(
            btn_row,
            text=i18n.t("sync.btn_download"),
            command=self._download,
            fg_color="transparent",
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_dim"],
            hover_color=COLORS["card_hover"],
            corner_radius=6, height=34, width=180,
            font=ctk.CTkFont(size=11),
            state="disabled",
        )
        self._download_btn.pack(side="left")

        # Progress label
        self._progress_lbl = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
        )
        self._progress_lbl.pack(anchor="w", pady=(8, 0))

        self._refresh_status()

    def _refresh_status(self):
        try:
            from services.drive_sync import get_sync_status
            status = get_sync_status()

            if not status["configured"]:
                self._status_lbl.configure(
                    text=i18n.t("sync.status_no_file"),
                    text_color=COLORS["gold"],
                )
                self._connect_btn.configure(state="disabled")
                self._upload_btn.configure(state="disabled")
                self._download_btn.configure(state="disabled")
            elif status["authenticated"]:
                self._status_lbl.configure(
                    text=i18n.t("sync.status_ok"),
                    text_color=COLORS["green"],
                )
                self._connect_btn.configure(
                    text=i18n.t("sync.btn_disconnect"),
                    fg_color=COLORS["border"],
                    text_color=COLORS["red"],
                    command=self._disconnect,
                )
                self._upload_btn.configure(state="normal", text_color=COLORS["text"])
                self._download_btn.configure(state="normal", text_color=COLORS["text"])
            else:
                self._status_lbl.configure(
                    text=i18n.t("sync.status_no_token"),
                    text_color=COLORS["text_dim"],
                )
                self._connect_btn.configure(state="normal")
                self._upload_btn.configure(state="disabled")
                self._download_btn.configure(state="disabled")
        except ImportError:
            self._status_lbl.configure(
                text="⚠ Instala: pip install google-api-python-client google-auth-oauthlib",
                text_color=COLORS["gold"],
            )

    def _connect(self):
        from services.drive_sync import is_configured, authenticate
        if not is_configured():
            self._progress_lbl.configure(
                text=i18n.t("sync.no_secret"), text_color=COLORS["gold"])
            return

        self._connect_btn.configure(state="disabled")
        self._progress_lbl.configure(
            text=i18n.t("sync.connecting"), text_color=COLORS["blue"])

        def _done(success, message):
            self.after(0, lambda: self._on_connect_done(success, message))

        authenticate(on_done=_done)

    def _on_connect_done(self, success: bool, message: str):
        self._progress_lbl.configure(
            text=message,
            text_color=COLORS["green"] if success else COLORS["red"],
        )
        self._refresh_status()
        self.after(3000, lambda: self._progress_lbl.configure(text=""))

    def _disconnect(self):
        from services.drive_sync import disconnect
        disconnect()
        self._refresh_status()
        self._progress_lbl.configure(text="")

    def _upload(self):
        from services.drive_sync import upload_all
        self._set_busy(True)

        def _progress(msg):
            self.after(0, lambda m=msg: self._progress_lbl.configure(
                text=m, text_color=COLORS["blue"]))

        def _work():
            result = upload_all(on_progress=_progress)
            n      = result["uploaded"]
            errors = result["errors"]
            if errors:
                msg   = i18n.t("sync.error", msg=errors[0])
                color = COLORS["red"]
            else:
                msg   = i18n.t("sync.upload_done", n=n)
                color = COLORS["green"]
            self.after(0, lambda: self._on_op_done(msg, color))

        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _download(self):
        from services.drive_sync import download_all
        self._set_busy(True)

        def _progress(msg):
            self.after(0, lambda m=msg: self._progress_lbl.configure(
                text=m, text_color=COLORS["blue"]))

        def _work():
            result = download_all(on_progress=_progress)
            n      = result["downloaded"]
            errors = result["errors"]
            if errors:
                msg   = i18n.t("sync.error", msg=errors[0])
                color = COLORS["red"]
            else:
                msg   = i18n.t("sync.download_done", n=n)
                color = COLORS["green"]
            self.after(0, lambda: self._on_op_done(msg, color))

        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self._upload_btn.configure(state=state)
        self._download_btn.configure(state=state)

    def _on_op_done(self, msg: str, color: str):
        self._set_busy(False)
        self._progress_lbl.configure(text=msg, text_color=color)
        self.after(5000, lambda: self._progress_lbl.configure(text=""))


# ── Steam Connect Panel ───────────────────────────────────────────────────────

class SteamConnectPanel(ctk.CTkFrame):
    """
    Steam account connection + wishlist import panel.
    Embedded in SettingsView.
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._settings = load_settings()
        self._importing = False
        self._build()

    def _build(self):
        # Section header
        ctk.CTkLabel(
            self, text=i18n.t("steam_connect.title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", pady=(24, 4))
        ctk.CTkFrame(
            self, fg_color=COLORS["border"], height=1, corner_radius=0,
        ).pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            self, text=i18n.t("steam_connect.desc"),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
            wraplength=420, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # ── Steam API Key ─────────────────────────────────────────
        ctk.CTkLabel(
            self, text=i18n.t("steam_connect.api_key_label"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", pady=(0, 3))
        ctk.CTkLabel(
            self, text=i18n.t("steam_connect.api_key_desc"),
            font=ctk.CTkFont(size=10),
            text_color=COLORS["blue"],
        ).pack(anchor="w", pady=(0, 6))

        key_row = ctk.CTkFrame(self, fg_color="transparent")
        key_row.pack(anchor="w", fill="x")

        self._steam_key_var = ctk.StringVar(
            value=self._settings.get("steam_api_key", "")
        )
        self._steam_key_entry = ctk.CTkEntry(
            key_row,
            textvariable=self._steam_key_var,
            placeholder_text="XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
            show="•",
            width=300, height=34,
            fg_color=COLORS["card"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
        )
        self._steam_key_entry.pack(side="left")

        self._key_eye_btn = ctk.CTkButton(
            key_row,
            text=i18n.t("settings.show_key"),
            width=90, height=34,
            fg_color="transparent",
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_dim"],
            hover_color=COLORS["card_hover"],
            corner_radius=6,
            font=ctk.CTkFont(size=11),
            command=self._toggle_key,
        )
        self._key_eye_btn.pack(side="left", padx=(8, 0))
        self._key_visible = False

        ctk.CTkButton(
            key_row,
            text="Guardar key",
            width=100, height=34,
            fg_color=COLORS["green"],
            text_color="#FFFFFF",
            hover_color="#4a8a22",
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._save_steam_key,
        ).pack(side="left", padx=(8, 0))

        # ── Account status ────────────────────────────────────────
        self._account_frame = ctk.CTkFrame(
            self,
            fg_color=COLORS["card"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
        )
        self._account_frame.pack(fill="x", pady=(14, 0))
        self._render_account_status()

        # ── Progress / feedback ───────────────────────────────────
        self._progress_lbl = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
        )
        self._progress_lbl.pack(anchor="w", pady=(8, 0))

    def _render_account_status(self):
        for w in self._account_frame.winfo_children():
            w.destroy()

        self._settings = load_settings()
        steam_id   = self._settings.get("steam_id64", "")
        steam_name = self._settings.get("steam_name", "")

        row = ctk.CTkFrame(self._account_frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=12)

        if steam_id and steam_name:
            # Connected state
            ctk.CTkLabel(
                row, text="🎮",
                font=ctk.CTkFont(size=22),
            ).pack(side="left", padx=(0, 10))

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True)

            ctk.CTkLabel(
                info,
                text=i18n.t("steam_connect.connected", name=steam_name),
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=COLORS["green"],
                anchor="w",
            ).pack(anchor="w")
            ctk.CTkLabel(
                info, text=f"SteamID64: {steam_id}",
                font=ctk.CTkFont(size=10),
                text_color=COLORS["text_dim"],
                anchor="w",
            ).pack(anchor="w")

            btn_col = ctk.CTkFrame(row, fg_color="transparent")
            btn_col.pack(side="right")

            ctk.CTkButton(
                btn_col,
                text=i18n.t("steam_connect.btn_import"),
                command=self._import_wishlist,
                fg_color=COLORS["blue"], text_color="#0a1929",
                hover_color="#4fa8d8", corner_radius=6,
                font=ctk.CTkFont(size=11, weight="bold"),
                height=32, width=200,
            ).pack(pady=(0, 6))

            ctk.CTkButton(
                btn_col,
                text=i18n.t("steam_connect.btn_disconnect"),
                command=self._disconnect_steam,
                fg_color="transparent",
                border_color=COLORS["border"], border_width=1,
                text_color=COLORS["text_dim"],
                hover_color=COLORS["card_hover"],
                corner_radius=6,
                font=ctk.CTkFont(size=10),
                height=28, width=200,
            ).pack()

        else:
            # Not connected state
            ctk.CTkLabel(
                row, text="🎮",
                font=ctk.CTkFont(size=22),
            ).pack(side="left", padx=(0, 10))

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True)

            ctk.CTkLabel(
                info,
                text=i18n.t("steam_connect.not_connected"),
                font=ctk.CTkFont(size=12),
                text_color=COLORS["text_dim"],
                anchor="w",
            ).pack(anchor="w")

            ctk.CTkButton(
                row,
                text=i18n.t("steam_connect.btn_connect"),
                command=self._connect_steam,
                fg_color="#1B2838",
                hover_color="#2a475e",
                text_color=COLORS["blue"],
                border_color=COLORS["blue"], border_width=1,
                corner_radius=6,
                font=ctk.CTkFont(size=12, weight="bold"),
                height=34, width=200,
            ).pack(side="right")

    # ── Actions ───────────────────────────────────────────────────

    def _toggle_key(self):
        self._key_visible = not self._key_visible
        self._steam_key_entry.configure(show="" if self._key_visible else "•")
        self._key_eye_btn.configure(
            text=i18n.t("settings.hide_key") if self._key_visible
                 else i18n.t("settings.show_key")
        )

    def _save_steam_key(self):
        settings = load_settings()
        settings["steam_api_key"] = self._steam_key_var.get().strip()
        save_settings(settings)
        self._settings = settings
        self._progress_lbl.configure(
            text="✓ Steam API key guardada", text_color=COLORS["green"])
        self.after(3000, lambda: self._progress_lbl.configure(text=""))

    def _connect_steam(self):
        api_key = self._steam_key_var.get().strip() or self._settings.get("steam_api_key", "")
        if not api_key:
            self._progress_lbl.configure(
                text="Primero guarda tu Steam API key arriba.",
                text_color=COLORS["gold"],
            )
            return

        self._progress_lbl.configure(
            text=i18n.t("steam_connect.connecting"),
            text_color=COLORS["blue"],
        )

        from services.steam_auth import login

        def _on_done(steam_id64, message):
            if not steam_id64:
                msgs = {
                    "timeout":    "Tiempo agotado. Inténtalo de nuevo.",
                    "failed":     "Verificación fallida. Inténtalo de nuevo.",
                }
                msg = msgs.get(message, f"Error: {message}")
                self.after(0, lambda: self._progress_lbl.configure(
                    text=msg, text_color=COLORS["red"]))
                return

            # Fetch player name
            from services.steam_wishlist import get_player_summary
            profile = get_player_summary(steam_id64, api_key)
            name    = profile["name"] if profile else steam_id64

            settings = load_settings()
            settings["steam_id64"]  = steam_id64
            settings["steam_name"]  = name
            save_settings(settings)
            self._settings = settings

            self.after(0, self._render_account_status)
            self.after(0, lambda: self._progress_lbl.configure(
                text=i18n.t("steam_connect.connected", name=name),
                text_color=COLORS["green"],
            ))

        login(on_done=_on_done)

    def _disconnect_steam(self):
        settings = load_settings()
        settings["steam_id64"] = ""
        settings["steam_name"] = ""
        save_settings(settings)
        self._settings = settings
        self._render_account_status()
        self._progress_lbl.configure(text="")

    def _import_wishlist(self):
        if self._importing:
            return
        self._importing = True

        settings = load_settings()
        steam_id = settings.get("steam_id64", "")
        api_key  = settings.get("steam_api_key", "")
        country  = settings.get("country", "mx")

        if not steam_id or not api_key:
            self._progress_lbl.configure(
                text="Conecta tu cuenta de Steam primero.",
                text_color=COLORS["gold"],
            )
            self._importing = False
            return

        def _progress(n, total, app_id):
            self.after(0, lambda: self._progress_lbl.configure(
                text=i18n.t("steam_connect.importing", n=n, total=total),
                text_color=COLORS["blue"],
            ))

        def _work():
            from services.steam_wishlist import import_wishlist
            try:
                result = import_wishlist(
                    steam_id, api_key, country,
                    on_progress=_progress,
                    skip_existing=True,
                )
                added = result["added"]
                msg = i18n.t("steam_connect.import_done",
                             added=added,
                             skipped=result["skipped"])
                color = COLORS["green"]

                # Auto-download covers for newly imported games
                if added > 0:
                    from services.steamgriddb import download_all_missing
                    import data.repository as repo2
                    settings2 = load_settings()
                    api_key2  = settings2.get("steamgriddb_key", "")
                    all_games = repo2.get_all()
                    self.after(0, lambda: self._progress_lbl.configure(
                        text=f"Downloading covers for {added} games...",
                        text_color=COLORS["blue"],
                    ))
                    def _cov_done(dl, fail):
                        self.after(0, lambda: self._progress_lbl.configure(
                            text=f"✓ Import done · {dl} covers downloaded",
                            text_color=COLORS["green"],
                        ))
                        self.after(5000, lambda: self._progress_lbl.configure(text=""))
                    download_all_missing(all_games, api_key2, on_done=_cov_done, max_workers=4)

            except Exception as e:
                msg   = i18n.t("steam_connect.import_error", msg=str(e))
                color = COLORS["red"]
            finally:
                self._importing = False
            self.after(0, lambda: self._progress_lbl.configure(text=msg, text_color=color))
            self.after(6000, lambda: self._progress_lbl.configure(text=""))

        import threading
        threading.Thread(target=_work, daemon=True).start()
