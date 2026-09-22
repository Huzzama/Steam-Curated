"""
The few animations the app actually uses — kept deliberately small.

* FadingStack   – a QStackedWidget whose page changes cross-fade with a
                  short vertical slide (direction follows sidebar order).
* slide_panel   – open/close the detail panel by animating its width.
* shake         – horizontal nudge on a form field that failed validation.
* fade_in       – one-shot opacity fade for freshly built content.

Everything else the old module had (pulse, shimmer, style-sheet swaps,
label flicker) has been removed: those were style-sheet hacks that fought
the global theme and raised RuntimeError on widgets deleted mid-animation.

All animations are owned by the widget they act on (parent=widget) so Qt
deletes them together, and they never touch a widget's styleSheet.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QParallelAnimationGroup, QPoint,
    QPropertyAnimation, QSequentialAnimationGroup, Qt, QTimer,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget

from ui.theme import DURATION

_EASE_OUT = QEasingCurve.Type.OutCubic
_SLIDE_PX = 14


def _stop(widget: QWidget, attr: str) -> None:
    anim = getattr(widget, attr, None)
    if anim is not None:
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


# ── page transitions ─────────────────────────────────────────────────────────

class FadingStack(QStackedWidget):
    """
    QStackedWidget with an animated `set_current(widget, direction)`.

    direction: +1 → new page slides up from below (moving down the sidebar)
               -1 → new page slides down from above
                0 → plain cross-fade
    """

    def __init__(self, parent: Optional[QWidget] = None, duration: int = DURATION["slow"]):
        super().__init__(parent)
        self._duration = duration
        self._anim: Optional[QParallelAnimationGroup] = None
        self._effect: Optional[QGraphicsOpacityEffect] = None
        self._pending: Optional[QWidget] = None

    def set_current(self, widget: QWidget, direction: int = 0) -> None:
        if widget is self.currentWidget():
            return
        if self._anim is not None and self._anim.state() == QAbstractAnimation.State.Running:
            # finish the running one instantly, then start the new one
            self._anim.stop()
            self._finish()

        old = self.currentWidget()
        self.setCurrentWidget(widget)
        if old is None or not self.isVisible() or self._duration <= 0:
            return

        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        self._effect = effect
        self._pending = widget

        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(self._duration)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(_EASE_OUT)

        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)

        if direction:
            start = widget.pos() + QPoint(0, _SLIDE_PX * direction)
            end   = widget.pos()
            slide = QPropertyAnimation(widget, b"pos", self)
            slide.setDuration(self._duration)
            slide.setStartValue(start)
            slide.setEndValue(end)
            slide.setEasingCurve(_EASE_OUT)
            group.addAnimation(slide)

        group.finished.connect(self._finish)
        self._anim = group
        group.start()

    def _finish(self) -> None:
        w = self._pending
        self._pending = None
        self._anim = None
        self._effect = None
        if w is None:
            return
        try:
            w.setGraphicsEffect(None)
            w.move(0, 0)
        except RuntimeError:
            pass


# ── detail panel ─────────────────────────────────────────────────────────────

def slide_panel(panel: QWidget, open_: bool, width: int,
                duration: int = DURATION["base"], on_done=None) -> None:
    """Animate `panel`'s maximumWidth between 0 and `width` (Qt lays it out
    for us). Hides the panel when closed so it stops receiving events."""
    _stop(panel, "_slide_anim")
    if open_:
        panel.setMinimumWidth(0)
        panel.setMaximumWidth(0)
        panel.show()
    start, end = (0, width) if open_ else (panel.width(), 0)

    anim = QPropertyAnimation(panel, b"maximumWidth", panel)
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(_EASE_OUT)

    def _done():
        panel._slide_anim = None
        try:
            if open_:
                panel.setMinimumWidth(width)
                panel.setMaximumWidth(width)
            else:
                panel.hide()
        except RuntimeError:
            return
        if on_done:
            on_done()

    anim.finished.connect(_done)
    panel._slide_anim = anim
    anim.start()


# ── feedback ─────────────────────────────────────────────────────────────────

def shake(widget: QWidget, amplitude: int = 6, duration: int = 320) -> None:
    """Horizontal nudge — used for invalid form fields."""
    _stop(widget, "_shake_anim")
    origin = widget.pos()
    seq = QSequentialAnimationGroup(widget)
    steps = [amplitude, -amplitude, amplitude // 2, -amplitude // 2, 0]
    for dx in steps:
        a = QPropertyAnimation(widget, b"pos", seq)
        a.setDuration(duration // len(steps))
        a.setEndValue(origin + QPoint(dx, 0))
        a.setEasingCurve(QEasingCurve.Type.InOutQuad)
        seq.addAnimation(a)

    def _done():
        widget._shake_anim = None
        try:
            widget.move(origin)
        except RuntimeError:
            pass

    seq.finished.connect(_done)
    widget._shake_anim = seq
    seq.start()


def fade_in(widget: QWidget, duration: int = DURATION["base"]) -> None:
    """One-shot opacity fade; removes the effect afterwards so the widget
    renders normally (opacity effects break some sub-pixel text)."""
    _stop(widget, "_fade_anim")
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    widget.show()

    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(_EASE_OUT)

    def _done():
        widget._fade_anim = None
        _clear_effect(widget)

    anim.finished.connect(_done)
    widget._fade_anim = anim
    anim.start()


def clear_layout(layout) -> None:
    """Remove and delete every item in a layout (widgets and sub-layouts)."""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())
