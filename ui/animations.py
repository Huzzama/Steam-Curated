"""
Micro-animation helpers — PySide6.
"""
from PySide6.QtWidgets import QLabel, QPushButton
from PySide6.QtCore import QTimer
from config import COLORS


def animate_value_change(label: QLabel, new_text: str):
    """Flash label to accent color briefly when its value updates."""
    label.setText(new_text)
    label.setStyleSheet(f"color:{COLORS['blue']}; background:transparent;")
    QTimer.singleShot(300, lambda: label.setStyleSheet(
        f"color:{COLORS['text']}; background:transparent;"))


def pulse_button(btn: QPushButton, times: int = 1):
    """Single pulse on a button for success feedback."""
    original_style = btn.styleSheet()
    bright = COLORS["blue"]

    def _on():
        btn.setStyleSheet(btn.styleSheet().replace(
            f"background:{COLORS['card']}", f"background:{bright}"))
        QTimer.singleShot(100, _off)

    def _off():
        btn.setStyleSheet(original_style)
        nonlocal times
        times -= 1
        if times > 0:
            QTimer.singleShot(100, _on)

    _on()