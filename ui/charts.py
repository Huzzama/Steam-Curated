"""
Small QPainter charts shared by Dashboard, Recap and History — no matplotlib.

    BarChart(labels, values, tone="accent", horizontal=False)   .set_data(labels, values, colors=None)
    DonutChart(slices)            slices = [(label, value, color), …]   .set_data(slices)
    Sparkline(values, tone)       .set_data(values)

Every chart is antialiased, uses theme colours only, writes numbers in the
mono face and text tokens (never in the series colour), and draws a muted
"no data" line when it has nothing to show. Heights are fixed per chart so
they sit predictably inside a Card; widths follow the layout.
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

import i18n
from ui.theme import C, SP, font

TONES = {
    "accent": C["accent"], "green": C["green"], "gold": C["gold"], "red": C["red"],
    "violet": C["violet"], "cyan": C["cyan"], "orange": C["orange"], "pink": C["pink"],
}

# Fixed categorical order for "nth series" colouring (never cycled past 8).
SERIES = [C["accent"], C["green"], C["gold"], C["violet"], C["cyan"], C["orange"], C["pink"], C["red"]]

_BAR_RADIUS = 4
_BAR_MAX_W = 44


def _fmt_default(v: float) -> str:
    return f"{v:,.0f}"


def _tone(tone: str) -> str:
    return TONES.get(tone, tone)


class _Chart(QWidget):
    """Common base: antialiased painter, value formatter, empty-state text."""

    def __init__(self, height: int, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._fmt: Callable[[float], str] = _fmt_default
        self._label_font = font("sm")
        self._value_font = font("xs", QFont.Weight.Bold, "mono")
        self._empty_text = i18n.t("dashboard.no_data")

    def set_formatter(self, fmt: Optional[Callable[[float], str]]) -> None:
        self._fmt = fmt or _fmt_default
        self.update()

    def set_empty_text(self, text: str) -> None:
        self._empty_text = text
        self.update()

    def _painter(self) -> QPainter:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        return p

    def _draw_empty(self, p: QPainter) -> None:
        p.setFont(self._label_font)
        p.setPen(QColor(C["text_muted"]))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)


class BarChart(_Chart):
    """Vertical (default) or horizontal bars with direct mono value labels.

    colors: optional per-bar colours (e.g. theme.PRIORITY values); otherwise
    every bar takes `tone` (one hue = one series, as a bar chart should).
    """

    def __init__(self, labels: Sequence[str] = (), values: Sequence[float] = (), tone: str = "accent",
                 horizontal: bool = False, colors: Optional[Sequence[str]] = None,
                 height: Optional[int] = None, row_height: int = 28, parent=None):
        self._horizontal = horizontal
        self._row_h = row_height
        self._explicit_h = height
        super().__init__(height or (row_height * max(1, len(labels)) + SP["sm"]) if horizontal else (height or 200),
                         parent)
        self._color = _tone(tone)
        self.set_data(labels, values, colors)

    def set_data(self, labels: Sequence[str], values: Sequence[float],
                 colors: Optional[Sequence[str]] = None) -> None:
        self._labels = [str(l) for l in labels]
        self._values = [float(v or 0) for v in values]
        self._colors = list(colors) if colors else None
        if self._horizontal and self._explicit_h is None:
            self.setMinimumHeight(self._row_h * max(1, len(self._labels)) + SP["sm"])
        self.update()

    def paintEvent(self, e) -> None:
        p = self._painter()
        if not self._values or max(self._values) <= 0:
            self._draw_empty(p)
            return
        if self._horizontal:
            self._paint_horizontal(p)
        else:
            self._paint_vertical(p)

    # ── vertical ─────────────────────────────────────────────────────────────
    def _paint_vertical(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        lm, vm = QFontMetrics(self._label_font), QFontMetrics(self._value_font)
        top = vm.height() + SP["xs"]
        bottom = h - lm.height() - SP["xs"]
        base_y = bottom
        n = len(self._values)
        slot = w / n
        bar_w = min(_BAR_MAX_W, slot * 0.62)
        vmax = max(self._values)
        scale = (base_y - top) / vmax

        # baseline (recessive)
        p.setPen(QPen(QColor(C["border"]), 1))
        p.drawLine(QPointF(0, base_y + 0.5), QPointF(w, base_y + 0.5))

        for i, v in enumerate(self._values):
            x = slot * i + (slot - bar_w) / 2
            bh = max(2.0 if v > 0 else 0.0, v * scale)
            color = QColor(self._colors[i] if self._colors and i < len(self._colors) else self._color)
            if bh > 0:
                r = min(_BAR_RADIUS, bar_w / 2, bh / 2)
                path = QPainterPath()
                path.addRoundedRect(QRectF(x, base_y - bh, bar_w, bh + r), r, r)
                p.save()
                p.setClipRect(QRectF(0, 0, w, base_y))
                p.fillPath(path, color)
                p.restore()
            # value on top (text token, mono); may overflow a narrow slot
            text = self._fmt(v)
            tw = vm.horizontalAdvance(text) + 4
            p.setFont(self._value_font)
            p.setPen(QColor(C["text_2"] if v > 0 else C["text_muted"]))
            tx = min(max(0.0, slot * i + (slot - max(slot, tw)) / 2), w - max(slot, tw))
            p.drawText(QRectF(tx, base_y - bh - vm.height() - 2, max(slot, tw), vm.height()),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, text)
            # label below
            p.setFont(self._label_font)
            p.setPen(QColor(C["text_dim"]))
            text = lm.elidedText(self._labels[i], Qt.TextElideMode.ElideRight, int(slot) + 2)
            p.drawText(QRectF(slot * i - 1, bottom + SP["xs"], slot + 2, lm.height()),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)

    # ── horizontal ───────────────────────────────────────────────────────────
    def _paint_horizontal(self, p: QPainter) -> None:
        w = self.width()
        lm, vm = QFontMetrics(self._label_font), QFontMetrics(self._value_font)
        label_w = min(int(w * 0.38), max((lm.horizontalAdvance(l) for l in self._labels), default=40) + SP["sm"])
        value_w = max((vm.horizontalAdvance(self._fmt(v)) for v in self._values), default=20) + SP["sm"]
        x0 = label_w + SP["sm"]
        avail = max(10, w - x0 - value_w)
        vmax = max(self._values)
        thick = min(12, self._row_h - 12)

        for i, v in enumerate(self._values):
            y = i * self._row_h
            cy = y + self._row_h / 2
            color = QColor(self._colors[i] if self._colors and i < len(self._colors) else self._color)
            # label
            p.setFont(self._label_font)
            p.setPen(QColor(C["text_2"]))
            text = lm.elidedText(self._labels[i], Qt.TextElideMode.ElideRight, label_w - 2)
            p.drawText(QRectF(0, y, label_w, self._row_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
            # track
            track = QPainterPath()
            track.addRoundedRect(QRectF(x0, cy - thick / 2, avail, thick), thick / 2, thick / 2)
            p.fillPath(track, QColor(C["surface_3"]))
            # bar
            bw = max(thick if v > 0 else 0, avail * v / vmax)
            if bw > 0:
                bar = QPainterPath()
                bar.addRoundedRect(QRectF(x0, cy - thick / 2, bw, thick), thick / 2, thick / 2)
                p.fillPath(bar, color)
            # value
            p.setFont(self._value_font)
            p.setPen(QColor(C["text"] if v > 0 else C["text_muted"]))
            p.drawText(QRectF(x0 + bw + SP["sm"], y, value_w + SP["md"], self._row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._fmt(v))


class DonutChart(_Chart):
    """Ring on the left (total in the centre), legend on the right.

    slices: [(label, value, color), …]. Slices with value 0 are kept in the
    legend (muted) but draw no arc.
    """

    RING = 112
    STROKE = 14

    def __init__(self, slices: Sequence[tuple[str, float, str]] = (), center_caption: str = "",
                 height: int = 148, parent=None):
        super().__init__(height, parent)
        self._center_font = font("xl", QFont.Weight.Bold, "mono")
        self._caption_font = font("2xs", QFont.Weight.Normal, "mono", 1.5)
        self._legend_value_font = font("sm", QFont.Weight.Bold, "mono")
        self._caption = center_caption
        self.set_data(slices)

    def set_data(self, slices: Sequence[tuple[str, float, str]], center_caption: Optional[str] = None) -> None:
        self._slices = [(str(l), float(v or 0), c) for l, v, c in slices]
        if center_caption is not None:
            self._caption = center_caption
        self.setMinimumHeight(max(self.RING + SP["lg"], len(self._slices) * 26 + SP["sm"]))
        self.update()

    def paintEvent(self, e) -> None:
        p = self._painter()
        total = sum(v for _, v, _ in self._slices)
        if total <= 0:
            self._draw_empty(p)
            return
        h = self.height()
        ring = self.RING
        cx, cy = ring / 2 + SP["xs"], h / 2
        r = (ring - self.STROKE) / 2
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)

        # arcs with a 2 px surface gap between segments
        gap_deg = (2.0 / (2 * 3.14159 * r)) * 360 if len([s for s in self._slices if s[1] > 0]) > 1 else 0
        start = 90.0
        for _, v, color in self._slices:
            if v <= 0:
                continue
            span = 360.0 * v / total
            pen = QPen(QColor(color), self.STROKE)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.drawArc(rect, int((start - gap_deg / 2) * 16), int(-(span - gap_deg) * 16))
            start -= span

        # centre: total + caption (text tokens)
        p.setPen(QColor(C["text"]))
        p.setFont(self._center_font)
        cm = QFontMetrics(self._center_font)
        cap_h = QFontMetrics(self._caption_font).height() if self._caption else 0
        block = cm.height() + cap_h
        p.drawText(QRectF(cx - r, cy - block / 2, 2 * r, cm.height()), Qt.AlignmentFlag.AlignCenter, self._fmt(total))
        if self._caption:
            p.setFont(self._caption_font)
            p.setPen(QColor(C["text_dim"]))
            p.drawText(QRectF(cx - r, cy - block / 2 + cm.height(), 2 * r, cap_h),
                       Qt.AlignmentFlag.AlignCenter, self._caption.upper())

        # legend
        lx = ring + SP["xl"]
        lw = self.width() - lx
        n = len(self._slices)
        row_h = 26
        ly = cy - n * row_h / 2
        lm, vm = QFontMetrics(self._label_font), QFontMetrics(self._legend_value_font)
        for i, (label, v, color) in enumerate(self._slices):
            y = ly + i * row_h
            dot = QRectF(lx, y + row_h / 2 - 4, 8, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color) if v > 0 else QColor(C["surface_3"]))
            p.drawEllipse(dot)
            value = f"{self._fmt(v)}  ·  {v / total * 100:.0f}%"
            vw = vm.horizontalAdvance(value)
            p.setFont(self._legend_value_font)
            p.setPen(QColor(C["text"] if v > 0 else C["text_muted"]))
            p.drawText(QRectF(lx + lw - vw - 2, y, vw + 2, row_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)
            p.setFont(self._label_font)
            p.setPen(QColor(C["text_2"] if v > 0 else C["text_muted"]))
            text = lm.elidedText(label, Qt.TextElideMode.ElideRight, int(lw - vw - 24))
            p.drawText(QRectF(lx + 16, y, lw - vw - 24, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


class Sparkline(_Chart):
    """Tiny line with a soft fill and a dot on the last point.

    zero_based=True (default) keeps 0 at the bottom so flat months read flat.
    """

    def __init__(self, values: Sequence[float] = (), tone: str = "accent", height: int = 40,
                 zero_based: bool = True, parent=None):
        super().__init__(height, parent)
        self._color = _tone(tone)
        self._zero = zero_based
        self.set_data(values)

    def set_data(self, values: Sequence[float]) -> None:
        self._values = [float(v or 0) for v in values]
        self.update()

    def paintEvent(self, e) -> None:
        p = self._painter()
        vals = self._values
        if len(vals) < 2:
            if vals:
                p.setPen(QPen(QColor(self._color), 2))
                p.drawLine(QPointF(0, self.height() / 2), QPointF(self.width(), self.height() / 2))
            return
        w, h = self.width(), self.height()
        vmax, vmin = max(vals), (min(0.0, min(vals)) if self._zero else min(vals))
        span = (vmax - vmin) or 1.0
        pad = 4
        step = (w - 2 * pad) / (len(vals) - 1)
        pts = [QPointF(pad + i * step, pad + (h - 2 * pad) * (1 - (v - vmin) / span)) for i, v in enumerate(vals)]

        area = QPainterPath(QPointF(pts[0].x(), h))
        for pt in pts:
            area.lineTo(pt)
        area.lineTo(pts[-1].x(), h)
        area.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        c = QColor(self._color)
        c.setAlpha(70); grad.setColorAt(0, c)
        c.setAlpha(0); grad.setColorAt(1, c)
        p.fillPath(area, grad)

        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        pen = QPen(QColor(self._color), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(line)
        p.setPen(QPen(QColor(C["surface_2"]), 2))
        p.setBrush(QColor(self._color))
        p.drawEllipse(pts[-1], 4, 4)
