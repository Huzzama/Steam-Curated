"""
Micro-animation helpers for Steam Curator.
Navigation is now handled by lift() in app_window — no slide needed.
"""
import customtkinter as ctk
from config import COLORS


def animate_value_change(label: ctk.CTkLabel, new_text: str):
    """Flash label to accent color briefly when its value updates."""
    label.configure(text=new_text, text_color=COLORS["blue"])
    label.after(300, lambda: label.configure(text_color=COLORS["text"]))


def pulse_button(btn: ctk.CTkButton, times: int = 1):
    """Single pulse on a button for success feedback."""
    original = btn.cget("fg_color")
    bright   = COLORS["blue"]

    def _on():
        btn.configure(fg_color=bright)
        btn.after(100, _off)

    def _off():
        btn.configure(fg_color=original)
        nonlocal times
        times -= 1
        if times > 0:
            btn.after(100, _on)

    _on()