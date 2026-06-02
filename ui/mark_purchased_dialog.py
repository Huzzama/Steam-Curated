"""
Dialog shown when user clicks "I bought this game".
Pre-fills price data from current game price info.
Lets user confirm edition (Standard / Deluxe / Ultimate / Other).
"""
import customtkinter as ctk
from datetime import datetime
from typing import Callable, Optional
from config import COLORS
from data.models import Game, Purchase
import data.purchase_repository as purchases
import data.repository as repo
import i18n


EDITIONS = ["Standard", "Deluxe", "Ultimate", "GOTY", "Complete", "Other"]


class MarkPurchasedDialog(ctk.CTkToplevel):

    def __init__(self, parent, game: Game,
                 on_success: Callable, **kwargs):
        super().__init__(parent, **kwargs)
        self._game      = game
        self._on_success = on_success

        self.title("Mark as Purchased")
        self.geometry("440x480")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["panel"])
        self.grab_set()
        self._build()

    def _build(self):
        P = 20

        # Title
        ctk.CTkLabel(
            self, text="I bought this game",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=P, pady=(16, 2))

        ctk.CTkLabel(
            self, text=self._game.name,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_dim"],
        ).pack(anchor="w", padx=P, pady=(0, 14))

        ctk.CTkFrame(self, fg_color=COLORS["border"], height=1,
                     corner_radius=0).pack(fill="x")

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="x", padx=P, pady=14)

        # ── Price paid ────────────────────────────────────────────
        self._field_label(content, "Price paid")
        price_row = ctk.CTkFrame(content, fg_color="transparent")
        price_row.pack(fill="x", pady=(0, 10))

        current = self._game.price.current if self._game.price else 0.0
        self._price_var = ctk.StringVar(value=f"{current:.2f}")
        ctk.CTkEntry(
            price_row, textvariable=self._price_var,
            width=140, height=34,
            fg_color=COLORS["card"], border_color=COLORS["border"],
            text_color=COLORS["text"],
        ).pack(side="left")

        currency = self._game.price.currency if self._game.price else "USD"
        ctk.CTkLabel(
            price_row, text=currency,
            font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"],
        ).pack(side="left", padx=(8, 0))

        # ── Base price ────────────────────────────────────────────
        self._field_label(content, "Full price (without discount)")
        base = self._game.price.base if self._game.price else current
        self._base_var = ctk.StringVar(value=f"{base:.2f}")
        ctk.CTkEntry(
            content, textvariable=self._base_var,
            width=140, height=34,
            fg_color=COLORS["card"], border_color=COLORS["border"],
            text_color=COLORS["text"],
        ).pack(anchor="w", pady=(0, 10))

        # ── Edition ───────────────────────────────────────────────
        self._field_label(content, "Edition")
        self._edition_var = ctk.StringVar(value="Standard")
        ctk.CTkOptionMenu(
            content,
            values=EDITIONS,
            variable=self._edition_var,
            width=200, height=34,
            fg_color=COLORS["card"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["card_hover"],
            text_color=COLORS["text"],
            dropdown_fg_color=COLORS["panel"],
            dropdown_hover_color=COLORS["card_hover"],
            dropdown_text_color=COLORS["text"],
        ).pack(anchor="w", pady=(0, 10))

        # ── Date ──────────────────────────────────────────────────
        self._field_label(content, "Purchase date")
        self._date_var = ctk.StringVar(
            value=datetime.now().strftime("%Y-%m-%d"))
        ctk.CTkEntry(
            content, textvariable=self._date_var,
            width=160, height=34,
            fg_color=COLORS["card"], border_color=COLORS["border"],
            text_color=COLORS["text"],
        ).pack(anchor="w", pady=(0, 4))

        ctk.CTkLabel(
            content, text="Format: YYYY-MM-DD",
            font=ctk.CTkFont(size=9), text_color=COLORS["text_dim"],
        ).pack(anchor="w")

        # ── Savings preview ───────────────────────────────────────
        self._savings_lbl = ctk.CTkLabel(
            content, text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["green"],
        )
        self._savings_lbl.pack(anchor="w", pady=(10, 0))
        self._price_var.trace_add("write", lambda *_: self._update_savings())
        self._base_var.trace_add("write",  lambda *_: self._update_savings())
        self._update_savings()

        # ── Buttons ───────────────────────────────────────────────
        ctk.CTkFrame(self, fg_color=COLORS["border"], height=1,
                     corner_radius=0).pack(fill="x", pady=(8, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=P, pady=14)

        ctk.CTkButton(
            btn_row, text="Cancel", command=self.destroy,
            fg_color="transparent", border_color=COLORS["border"],
            border_width=1, text_color=COLORS["text_dim"],
            hover_color=COLORS["card_hover"], corner_radius=6,
            height=34, width=86,
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="✓ Confirm purchase",
            command=self._confirm,
            fg_color=COLORS["green"], text_color="#000",
            hover_color="#86efac", corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34, width=160,
        ).pack(side="right")

    def _field_label(self, parent, text: str):
        ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", pady=(8, 3))

    def _update_savings(self):
        try:
            paid = float(self._price_var.get())
            base = float(self._base_var.get())
            saved = base - paid
            currency = self._game.price.currency if self._game.price else ""
            if saved > 0:
                self._savings_lbl.configure(
                    text=f"You saved ${saved:,.2f} {currency} ({int(saved/base*100)}% off)",
                    text_color=COLORS["green"],
                )
            else:
                self._savings_lbl.configure(text="")
        except (ValueError, ZeroDivisionError):
            self._savings_lbl.configure(text="")

    def _confirm(self):
        try:
            paid    = float(self._price_var.get())
            base    = float(self._base_var.get())
            date    = self._date_var.get().strip()
            edition = self._edition_var.get()
            currency = self._game.price.currency if self._game.price else "USD"
            disc_pct = max(0, int((1 - paid / base) * 100)) if base > 0 else 0

            purchase = Purchase(
                app_id       = self._game.app_id,
                name         = self._game.name,
                purchased_at = date,
                price_paid   = paid,
                base_price   = base,
                currency     = currency,
                discount_pct = disc_pct,
                edition      = edition,
                saved        = max(0.0, base - paid),
            )
            purchases.add(purchase)

            # Move game from Wishlist to Comprado
            self._game.status = "Comprado"
            repo.update(self._game)

            self._on_success(purchase)
            self.destroy()

        except ValueError:
            ctk.CTkLabel(
                self, text="Invalid price or date format.",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["red"],
            ).pack(pady=(0, 8))
