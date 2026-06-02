import customtkinter as ctk
import threading
from typing import Optional
from config import COLORS, PRIORITY_OPTIONS
from data.models import Game
import data.repository as repo
import services.steam_api as steam
import services.steamgriddb as sgdb
import services.steamdb_scraper as steamdb
import i18n
from ui.settings_loader import get_settings

MAX_RESULTS = 5


class AddGameDialog(ctk.CTkToplevel):

    def __init__(self, parent, on_success: callable, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_success       = on_success
        self._fetched_data    = None
        self._fetched_price   = None
        self._fetched_history = None
        self._row_frames: list = []

        self.title(i18n.t("add_game.title"))
        self.geometry("540x580")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["panel"])
        self.grab_set()
        self._build()

    def _build(self):
        P = 18

        # ── Title ────────────────────────────────────────────────
        ctk.CTkLabel(
            self, text=i18n.t("add_game.title"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=P, pady=(12, 4))

        # ── Search ───────────────────────────────────────────────
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=P)

        self._query_var = ctk.StringVar()
        self._entry = ctk.CTkEntry(
            row, textvariable=self._query_var,
            placeholder_text=i18n.t("add_game.search_appid"),
            height=32, fg_color=COLORS["card"],
            border_color=COLORS["border"], text_color=COLORS["text"],
        )
        self._entry.pack(side="left", fill="x", expand=True)
        self._entry.bind("<Return>", lambda e: self._search())
        self._entry.focus()

        self._search_btn = ctk.CTkButton(
            row, text=i18n.t("add_game.search_btn"),
            width=72, height=32,
            fg_color=COLORS["blue"], text_color="#0a1929",
            hover_color="#4fa8d8", corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._search,
        )
        self._search_btn.pack(side="left", padx=(6, 0))

        # ── Status ───────────────────────────────────────────────
        self._status = ctk.CTkLabel(
            self, text=i18n.t("add_game.hint"),
            font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"],
        )
        self._status.pack(anchor="w", padx=P, pady=(3, 0))

        # ── Results label ────────────────────────────────────────
        ctk.CTkLabel(
            self, text=i18n.t("add_game.section_results"),
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=COLORS["text_dim"],
        ).pack(anchor="w", padx=P, pady=(7, 2))

        # ── 5 fixed result rows ──────────────────────────────────
        box = ctk.CTkFrame(
            self, fg_color=COLORS["card"],
            corner_radius=8, border_width=1, border_color=COLORS["border"],
        )
        box.pack(fill="x", padx=P)

        for i in range(MAX_RESULTS):
            if i > 0:
                ctk.CTkFrame(box, fg_color=COLORS["border"], height=1, corner_radius=0).pack(fill="x")

            r = ctk.CTkFrame(box, fg_color="transparent", height=30, corner_radius=0)
            r.pack(fill="x")
            r.pack_propagate(False)

            id_lbl = ctk.CTkLabel(r, text="", width=64,
                                  font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"], anchor="w")
            id_lbl.pack(side="left", padx=(8, 0))

            name_lbl = ctk.CTkLabel(r, text="", anchor="w",
                                    font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"])
            name_lbl.pack(side="left", fill="x", expand=True, padx=4)

            price_lbl = ctk.CTkLabel(r, text="", width=86,
                                     font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"], anchor="e")
            price_lbl.pack(side="right", padx=8)

            r._data = None
            r._id_lbl    = id_lbl
            r._name_lbl  = name_lbl
            r._price_lbl = price_lbl

            for w in (r, id_lbl, name_lbl, price_lbl):
                w.bind("<Button-1>", lambda e, fr=r: self._select_row(fr))
                w.bind("<Enter>",    lambda e, fr=r: self._hover(fr, True))
                w.bind("<Leave>",    lambda e, fr=r: self._hover(fr, False))

            self._row_frames.append(r)

        # ── Preview label ────────────────────────────────────────
        ctk.CTkLabel(
            self, text=i18n.t("add_game.section_preview"),
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=COLORS["text_dim"],
        ).pack(anchor="w", padx=P, pady=(7, 2))

        # ── Preview grid (2 cols, 3 rows) ─────────────────────────
        prev_frame = ctk.CTkFrame(
            self, fg_color=COLORS["card"],
            corner_radius=8, border_width=1, border_color=COLORS["border"],
        )
        prev_frame.pack(fill="x", padx=P)

        self._prev_labels: dict[str, ctk.CTkLabel] = {}
        grid = ctk.CTkFrame(prev_frame, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=5)
        for col in range(4):
            grid.columnconfigure(col, weight=1 if col % 2 else 0,
                                 minsize=100 if col % 2 == 0 else 0)

        defs = [
            ("name",    i18n.t("game.name")),
            ("genre",   i18n.t("game.genre")),
            ("year",    i18n.t("game.year")),
            ("dev",     i18n.t("game.developer")),
            ("price",   i18n.t("game.price_current")),
            ("history", i18n.t("game.price_low")),
        ]
        for idx, (key, label) in enumerate(defs):
            c = (idx % 2) * 2
            rr = idx // 2
            ctk.CTkLabel(grid, text=f"{label}:", anchor="w",
                         font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"],
                         ).grid(row=rr, column=c, sticky="w", pady=1)
            lbl = ctk.CTkLabel(grid, text="—", anchor="w",
                               font=ctk.CTkFont(size=10), text_color=COLORS["text"])
            lbl.grid(row=rr, column=c + 1, sticky="w", padx=(3, 14), pady=1)
            self._prev_labels[key] = lbl

        # ── Priority + Notes side by side ─────────────────────────
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=P, pady=(8, 0))
        bottom.columnconfigure(0, weight=0)
        bottom.columnconfigure(1, weight=1)

        # Priority (left column)
        prio_col = ctk.CTkFrame(bottom, fg_color="transparent")
        prio_col.grid(row=0, column=0, sticky="nw", padx=(0, 12))

        ctk.CTkLabel(prio_col, text=i18n.t("game.priority"),
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLORS["text"]).pack(anchor="w", pady=(0, 4))

        self._priority_var = ctk.StringVar(value="B")
        p_row = ctk.CTkFrame(prio_col, fg_color="transparent")
        p_row.pack(anchor="w")
        from config import PRIORITY_COLORS
        for p in PRIORITY_OPTIONS:
            c = PRIORITY_COLORS.get(p, "#666")
            btn = ctk.CTkButton(
                p_row, text=p, width=38, height=28,
                fg_color=c if p == "B" else "transparent",
                text_color="#fff", hover_color=c,
                border_color=c, border_width=1, corner_radius=5,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda pv=p: self._set_priority(pv),
            )
            btn.pack(side="left", padx=(0, 4))
            self.__dict__[f"_pb_{p}"] = btn

        # Notes (right column)
        notes_col = ctk.CTkFrame(bottom, fg_color="transparent")
        notes_col.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(notes_col, text=i18n.t("game.notes"),
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLORS["text"]).pack(anchor="w", pady=(0, 4))
        self._notes = ctk.CTkTextbox(
            notes_col, height=56,
            fg_color=COLORS["card"], border_color=COLORS["border"],
            border_width=1, text_color=COLORS["text"],
        )
        self._notes.pack(fill="x")

        # ── Cancel / Save ────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=P, pady=(10, 12))

        ctk.CTkButton(
            btn_row, text=i18n.t("actions.cancel"), command=self.destroy,
            fg_color="transparent", border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_dim"], hover_color=COLORS["card_hover"],
            corner_radius=6, height=32, width=82,
        ).pack(side="left")

        self._save_btn = ctk.CTkButton(
            btn_row, text=i18n.t("actions.save"), command=self._save,
            fg_color=COLORS["blue"], text_color="#0a1929",
            hover_color="#4fa8d8", corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32, width=110, state="disabled",
        )
        self._save_btn.pack(side="right")

    # ─────────────────────────────────────────────────────────────

    def _hover(self, frame, entering: bool):
        if frame._data is None:
            return
        frame.configure(fg_color=COLORS["card_hover"] if entering else "transparent")

    def _select_row(self, frame):
        if frame._data is None:
            return
        result = frame._data
        for r in self._row_frames:
            if r._data is not None:
                is_sel = r is frame
                r.configure(fg_color=COLORS["card_hover"] if is_sel else "transparent")
                r._name_lbl.configure(
                    text_color=COLORS["blue"] if is_sel else COLORS["text"],
                    font=ctk.CTkFont(size=11, weight="bold" if is_sel else "normal"),
                )
        self._status.configure(
            text=i18n.t("add_game.selected", name=result["name"]),
            text_color=COLORS["blue"],
        )
        self._fetch_details(result["id"])

    def _populate_rows(self, results: list):
        for i, frame in enumerate(self._row_frames):
            if i < len(results):
                r = results[i]
                frame._data = r
                frame._id_lbl.configure(text=f"#{r['id']}", text_color=COLORS["text_dim"])
                frame._name_lbl.configure(text=r["name"], text_color=COLORS["text"],
                                          font=ctk.CTkFont(size=11))
                if r.get("price") is not None:
                    pt = (f"${r['price']:,.0f} {r['currency']}"
                          if r["price"] > 0 else i18n.t("add_game.free"))
                    frame._price_lbl.configure(
                        text=pt,
                        text_color=COLORS["green"] if r["price"] > 0 else COLORS["blue"],
                    )
                else:
                    frame._price_lbl.configure(text="")
            else:
                frame._data = None
                frame._id_lbl.configure(text="")
                frame._name_lbl.configure(text="", text_color=COLORS["text_dim"])
                frame._price_lbl.configure(text="")

    def _search(self):
        query = self._query_var.get().strip()
        if not query:
            return
        if query.isdigit():
            self._status.configure(text=i18n.t("add_game.fetching"),
                                   text_color=COLORS["text_dim"])
            self._fetch_details(query)
            return
        self._status.configure(text=i18n.t("add_game.searching"),
                               text_color=COLORS["text_dim"])
        self._search_btn.configure(state="disabled")
        self._save_btn.configure(state="disabled")
        self._fetched_data = None
        self._populate_rows([])
        def _do_search():
            settings = get_settings()
            results = steam.search_games(query, limit=MAX_RESULTS, cc=settings.get('country', 'mx'))
            self.after(0, lambda: self._show_results(results))
        threading.Thread(target=_do_search, daemon=True).start()

    def _show_results(self, results: list):
        self._search_btn.configure(state="normal")
        if not results:
            self._status.configure(text=i18n.t("add_game.error_not_found"),
                                   text_color=COLORS["red"])
            return
        self._populate_rows(results)
        self._status.configure(
            text=i18n.t("add_game.select_hint", n=len(results)),
            text_color=COLORS["text_dim"],
        )

    def _fetch_details(self, app_id: str):
        def _work():
            settings = get_settings()
            data = steam.get_app_details(app_id, country=settings.get("country", "mx"))
            if not data:
                self.after(0, lambda: self._status.configure(
                    text=i18n.t("add_game.error_api"), text_color=COLORS["red"]))
                return
            meta    = steam.parse_metadata(data)
            meta["app_id"] = app_id
            price   = steam.parse_price(data)
            history = steamdb.get_price_history(app_id)
            self._fetched_data    = meta
            self._fetched_price   = price
            self._fetched_history = history
            self.after(0, lambda: self._update_preview(meta, price, history))
        threading.Thread(target=_work, daemon=True).start()

    def _update_preview(self, meta, price, history):
        self._prev_labels["name"].configure(text=meta.get("name", "—"))
        self._prev_labels["genre"].configure(text=meta.get("genre", "—"))
        self._prev_labels["year"].configure(text=str(meta.get("release_year") or "—"))
        self._prev_labels["dev"].configure(text=meta.get("developer", "—"))
        if price:
            pt = f"${price.current:,.0f} {price.currency}"
            if price.discount_pct:
                pt += f" (-{price.discount_pct}%)"
            self._prev_labels["price"].configure(
                text=pt, text_color=COLORS["green"] if price.is_on_sale else COLORS["text"])
        if history and history.all_time_low:
            ht = f"${history.all_time_low:,.0f}"
            if history.all_time_low_date:
                ht += f" · {history.all_time_low_date}"
            self._prev_labels["history"].configure(text=ht, text_color=COLORS["blue"])
        self._status.configure(text=i18n.t("add_game.data_ok"), text_color=COLORS["green"])
        self._save_btn.configure(state="normal")

    def _set_priority(self, p: str):
        from config import PRIORITY_COLORS
        self._priority_var.set(p)
        for pr in PRIORITY_OPTIONS:
            c = PRIORITY_COLORS.get(pr, "#666")
            btn = self.__dict__.get(f"_pb_{pr}")
            if btn:
                btn.configure(fg_color=c if pr == p else "transparent")

    def _save(self):
        if not self._fetched_data:
            return
        meta  = self._fetched_data
        notes = self._notes.get("1.0", "end").strip()
        game = Game(
            id=0,
            name=meta.get("name", ""),
            app_id=meta.get("app_id", ""),
            steam_url=meta.get("steam_url", ""),
            genre=meta.get("genre", ""),
            release_year=meta.get("release_year", 0),
            developer=meta.get("developer", ""),
            publisher=meta.get("publisher", ""),
            categories=meta.get("categories", ""),
            short_description=meta.get("short_description", ""),
            priority=self._priority_var.get(),
            status="Wishlist",
            price=self._fetched_price,
            price_history=self._fetched_history,
            notes=notes,
        )
        repo.add(game)
        settings = get_settings()
        api_key  = settings.get("steamgriddb_key", "")

        # Always try — steamgriddb.py uses Steam CDN fallback when no key
        def _dl():
            cover = sgdb.download_cover(game.app_id, api_key, game.name)
            if cover:
                game.cover_path = cover
                repo.update(game)
        threading.Thread(target=_dl, daemon=True).start()

        self.on_success()
        self.destroy()