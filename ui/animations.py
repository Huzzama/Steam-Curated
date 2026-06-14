from __future__ import annotations
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QLabel, QPushButton, QWidget, QGraphicsOpacityEffect
)
from PySide6.QtCore import (
    QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRect,
    QAbstractAnimation, Qt, QParallelAnimationGroup
)

from config import COLORS


# ── Nav order — determines slide direction ────────────────────────────────────

_NAV_ORDER = [
    "wishlist", "library", "dashboard", "deals",
    "non_steam", "history", "recap", "settings",
]


def nav_direction(from_key: str, to_key: str) -> int:
    """Return +1 if navigating DOWN (new view from below), -1 if UP (from above)."""
    try:
        fi = _NAV_ORDER.index(from_key)
        ti = _NAV_ORDER.index(to_key)
        return 1 if ti > fi else -1
    except ValueError:
        return 1  # unknown key → default to down


# ── Internal helpers ──────────────────────────────────────────────────────────

def _stop_anim(widget: QWidget, attr: str) -> None:
    anim = getattr(widget, attr, None)
    if anim is None:
        return
    try:
        if anim.state() == QAbstractAnimation.State.Running:
            anim.stop()
    except RuntimeError:
        pass
    setattr(widget, attr, None)


def _clear_effect(widget: QWidget) -> None:
    try:
        if widget.graphicsEffect() is not None:
            widget.setGraphicsEffect(None)
    except RuntimeError:
        pass


def _safe_hide(widget: QWidget) -> None:
    try:
        _clear_effect(widget)
        widget.hide()
    except RuntimeError:
        pass


# ── Core: directional slide transition ───────────────────────────────────────

def slide_transition(old: Optional[QWidget], new: QWidget,
                     direction: int = 1, duration: int = 280) -> None:
    """Directional slide between two views sharing a parent container.

    direction: +1 = new comes from BELOW (navigating down)
               -1 = new comes from ABOVE (navigating up)

    Uses setGeometry() + QPropertyAnimation on b"pos" — NOT QGraphicsOpacityEffect.
    setGeometry is used instead of move() so the widget always has the correct
    size regardless of what a previous layout pass may have assigned.
    """
    if not new or (old and old is new):
        return

    container = new.parent()
    if container is None:
        _safe_hide(old)
        try:
            new.show()
        except RuntimeError:
            pass
        return

    rect = container.rect()
    w    = rect.width()  or 800
    h    = rect.height() or 600

    # Stop in-flight animations on both views
    _stop_anim(new, "_slide_anim")
    if old:
        _stop_anim(old, "_slide_anim")

    # Remove any lingering opacity effects
    _clear_effect(new)
    if old:
        _clear_effect(old)

    # ── New view: place off-screen, slide to (0, 0) ───────────────────────────
    # +direction → starts below screen;  -direction → starts above screen
    new.setGeometry(0, h * direction, w, h)
    new.show()
    new.raise_()

    anim_new = QPropertyAnimation(new, b"pos", new)
    anim_new.setStartValue(QPoint(0, h * direction))
    anim_new.setEndValue(QPoint(0, 0))
    anim_new.setDuration(duration)
    anim_new.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _on_new_done() -> None:
        try:
            new.setGeometry(0, 0, w, h)   # snap to exact final rect
            new._slide_anim = None
        except RuntimeError:
            pass

    anim_new.finished.connect(_on_new_done)
    new._slide_anim = anim_new

    # ── Old view: slide from (0, 0) to off-screen ─────────────────────────────
    if old and old.isVisible():
        old.setGeometry(0, 0, w, h)
        old.raise_()
        new.raise_()   # keep new on top

        anim_old = QPropertyAnimation(old, b"pos", old)
        anim_old.setStartValue(QPoint(0, 0))
        anim_old.setEndValue(QPoint(0, -h * direction))
        anim_old.setDuration(duration)
        anim_old.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on_old_done() -> None:
            try:
                old.hide()
                old.setGeometry(0, 0, w, h)   # reset for next show
                old._slide_anim = None
            except RuntimeError:
                pass

        anim_old.finished.connect(_on_old_done)
        old._slide_anim = anim_old
        anim_old.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)

    anim_new.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


def safe_show_view(old: Optional[QWidget], new: QWidget,
                   from_key: str = "", to_key: str = "",
                   duration: int = 280) -> None:
    """Pure animation entry point for view navigation.

    Does NOT call refresh() — the caller (AppWindow) is responsible for
    deciding when to refresh based on dirty flags.
    Only determines direction and delegates to slide_transition().
    """
    direction = nav_direction(from_key, to_key)
    slide_transition(old, new, direction=direction, duration=duration)


# ── Detail panel: slide from right ───────────────────────────────────────────

def slide_in_right(panel: QWidget, width: int, duration: int = 220) -> None:
    """Slide the detail panel in from the right edge (width animation)."""
    _stop_anim(panel, "_slide_anim")
    _clear_effect(panel)

    panel.setFixedWidth(0)
    panel.show()

    anim = QPropertyAnimation(panel, b"minimumWidth", panel)
    anim.setStartValue(0)
    anim.setEndValue(width)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _done():
        try:
            panel._slide_anim = None
        except RuntimeError:
            pass

    anim.finished.connect(_done)
    panel._slide_anim = anim
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


def slide_out_right(panel: QWidget, duration: int = 180,
                    on_done: Optional[Callable] = None) -> None:
    """Slide the detail panel out to the right."""
    _stop_anim(panel, "_slide_anim")
    _clear_effect(panel)

    current_w = panel.width()

    anim = QPropertyAnimation(panel, b"minimumWidth", panel)
    anim.setStartValue(current_w)
    anim.setEndValue(0)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.InCubic)

    def _done():
        try:
            panel.hide()
            panel.setMinimumWidth(0)
            panel.setFixedWidth(current_w)
            panel._slide_anim = None
        except RuntimeError:
            pass
        if on_done:
            on_done()

    anim.finished.connect(_done)
    panel._slide_anim = anim
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


# ── Layout cleanup ────────────────────────────────────────────────────────────

def clear_layout(layout) -> None:
    """Safely remove and delete all widgets from a layout."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.hide()
            widget.deleteLater()


# ── Kept for back-compat (used by detail panel fade) ─────────────────────────

def fade_in(widget: QWidget, duration: int = 180) -> None:
    """Fade a small widget (not a full view) in."""
    _stop_anim(widget, "_fade_anim")
    _clear_effect(widget)
    widget.show()

    fx = QGraphicsOpacityEffect(widget)
    fx.setOpacity(0.0)
    widget.setGraphicsEffect(fx)

    anim = QPropertyAnimation(fx, b"opacity", widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _done():
        _clear_effect(widget)
        try:
            widget._fade_anim = None
        except RuntimeError:
            pass

    anim.finished.connect(_done)
    widget._fade_anim = anim
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


def fade_out(widget: QWidget, duration: int = 140,
             on_done: Optional[Callable] = None) -> None:
    """Fade a small widget out and hide it."""
    _stop_anim(widget, "_fade_anim")
    _clear_effect(widget)

    fx = QGraphicsOpacityEffect(widget)
    fx.setOpacity(1.0)
    widget.setGraphicsEffect(fx)

    anim = QPropertyAnimation(fx, b"opacity", widget)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.InCubic)

    def _done():
        try:
            widget.hide()
        except RuntimeError:
            pass
        _clear_effect(widget)
        try:
            widget._fade_anim = None
        except RuntimeError:
            pass
        if on_done:
            on_done()

    anim.finished.connect(_done)
    widget._fade_anim = anim
    anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)


# ── Button / card micro-animations ───────────────────────────────────────────

def _safe_set_style(widget: QWidget, style: str) -> None:
    try:
        widget.setStyleSheet(style)
    except RuntimeError:
        pass


def animate_value_change(label: QLabel, new_text: str,
                         accent: str = COLORS["blue"]) -> None:
    try:
        label.setText(new_text)
        label.setStyleSheet(f"color:{accent}; background:transparent;")
        QTimer.singleShot(350, lambda: _safe_set_style(
            label, f"color:{COLORS['text']}; background:transparent;"))
    except RuntimeError:
        pass


def pulse_button(btn: QPushButton, times: int = 1,
                 color: str = COLORS["blue"]) -> None:
    try:
        original_style = btn.styleSheet()
    except RuntimeError:
        return

    def _on():
        try:
            btn.setStyleSheet(original_style.replace(
                COLORS["card"], color).replace("transparent", color))
            QTimer.singleShot(90, _off)
        except RuntimeError:
            pass

    def _off():
        try:
            btn.setStyleSheet(original_style)
        except RuntimeError:
            return
        nonlocal times
        times -= 1
        if times > 0:
            QTimer.singleShot(90, _on)

    _on()


def shimmer_card(widget: QWidget, accent: str = COLORS["blue"],
                 duration: int = 400) -> None:
    try:
        original = widget.styleSheet()
        name = widget.objectName()
        selector = f"QFrame#{name}" if name else "QFrame"
        glow = f"\n{selector} {{ border: 1.5px solid {accent}; }}\n"
        widget.setStyleSheet(original + glow)
        QTimer.singleShot(duration, lambda: _safe_set_style(widget, original))
    except RuntimeError:
        pass


def shake_widget(widget: QWidget, amplitude: int = 6,
                 duration: int = 300) -> None:
    try:
        orig = widget.pos()
    except RuntimeError:
        return
    steps = 5
    step_ms = duration // (steps * 2)

    def _step(n: int):
        try:
            if n >= steps * 2:
                widget.move(orig)
                return
            dx = amplitude if (n % 2 == 0) else -amplitude
            widget.move(orig + QPoint(dx, 0))
            QTimer.singleShot(step_ms, lambda: _step(n + 1))
        except RuntimeError:
            pass

    _step(0)


def nav_click_feedback(btn: QPushButton) -> None:
    try:
        original = btn.styleSheet()
        bright = original.replace(
            COLORS.get("card_hover", "#1e1e24"), "#2a2a35")
        btn.setStyleSheet(bright)
        QTimer.singleShot(80, lambda: _safe_set_style(btn, original))
    except RuntimeError:
        pass