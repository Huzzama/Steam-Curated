import customtkinter as ctk
from PIL import Image, ImageDraw
from pathlib import Path
from typing import Optional, Callable
from config import COLORS, PRIORITY_COLORS
from data.models import Game
import i18n


# ── Image helpers ─────────────────────────────────────────────────────────────

def make_ctk_image(path: Optional[str], size=(90, 135)) -> ctk.CTkImage:
    """Load image via global LRU cache."""
    from ui.image_cache import get as _cache_get
    return _cache_get(path, size)


def _placeholder_image(size=(90, 135)) -> ctk.CTkImage:
    img  = Image.new("RGB", size, color=(20, 20, 24))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size[0]-1, size[1]-1], outline=(39, 39, 42), width=1)
    draw.text((size[0]//2, size[1]//2), "?", fill=(96, 165, 250), anchor="mm")
    return ctk.CTkImage(light_image=img, dark_image=img, size=size)


# ── StatCard ──────────────────────────────────────────────────────────────────

class StatCard(ctk.CTkFrame):
    """
    Metric card with colored accent border, icon, and animated value.
    accent_color drives the left border, icon, and value color.
    """

    def __init__(self, parent, label: str, value: str,
                 value_color: str = None, icon: str = "",
                 accent: str = None, **kwargs):
        accent = accent or value_color or COLORS["blue"]

        super().__init__(
            parent,
            fg_color=COLORS["card"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )

        # Colored left accent bar
        ctk.CTkFrame(
            self, fg_color=accent,
            width=3, corner_radius=0,
        ).place(x=0, y=0, relheight=1)

        # Icon + label row
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(anchor="w", padx=(14, 8), pady=(10, 0))

        if icon:
            ctk.CTkLabel(
                top, text=icon,
                font=ctk.CTkFont(size=13),
                text_color=accent,
            ).pack(side="left", padx=(0, 4))

        ctk.CTkLabel(
            top, text=label,
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_dim"],
        ).pack(side="left")

        # Value
        self._value_label = ctk.CTkLabel(
            self, text=value,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=accent,
        )
        self._value_label.pack(anchor="w", padx=14, pady=(1, 10))

    def set_value(self, value: str, color: str = None):
        from ui.animations import animate_value_change
        if self._value_label.cget("text") != value:
            animate_value_change(self._value_label, value)
        if color:
            self._value_label.configure(text_color=color)


# ── SteamButton ───────────────────────────────────────────────────────────────

class SteamButton(ctk.CTkButton):
    """Primary button with micro-animation on hover."""

    def __init__(self, parent, text: str, command=None, style="primary", **kwargs):
        palettes = {
            "primary": (COLORS["blue"],   "#93c5fd", COLORS["bg"]),
            "success": (COLORS["green"],  "#86efac", "#000"),
            "ghost":   ("transparent",    COLORS["card_hover"], COLORS["text"]),
        }
        fg, hover, txt = palettes.get(style, palettes["primary"])

        super().__init__(
            parent,
            text=text,
            command=command,
            fg_color=fg,
            hover_color=hover,
            text_color=txt,
            border_color=COLORS["border"] if style == "ghost" else fg,
            border_width=1 if style == "ghost" else 0,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            **kwargs,
        )


# ── SectionHeader ─────────────────────────────────────────────────────────────

class SectionHeader(ctk.CTkFrame):
    def __init__(self, parent, title: str, action_text: str = None,
                 action_cmd=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        ctk.CTkLabel(
            self, text=title,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_dim"],
        ).pack(side="left")

        if action_text:
            SteamButton(
                self, text=action_text, command=action_cmd,
                style="ghost", height=26, width=100,
            ).pack(side="right")


# ── DealBanner ────────────────────────────────────────────────────────────────

class DealBanner(ctk.CTkFrame):
    """Buy-now alert banner."""

    def __init__(self, parent, game: Game, **kwargs):
        super().__init__(
            parent,
            fg_color="#0a1f0a",
            corner_radius=8,
            border_width=1,
            border_color="#1a4a1a",
            **kwargs,
        )
        ctk.CTkLabel(
            self,
            text=f"🔥  {game.name} — {i18n.t('recommendation.buy_now')}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["green"],
        ).pack(side="left", padx=14, pady=10)

        if game.price and game.price_history:
            info = (f"${game.price.current:,.0f} {game.price.currency} · "
                    f"mín: ${game.price_history.all_time_low:,.0f}")
            ctk.CTkLabel(
                self, text=info,
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_dim"],
            ).pack(side="left", padx=4)