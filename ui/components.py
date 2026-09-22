"""
The widget library every view is built from. Nothing in ui/*_view.py should
call setStyleSheet() — pick a component, set a property, done.

Text        label(text, role) · Eyebrow · Divider
Buttons     Button · IconButton · Segmented · ChipGroup
Surfaces    Card · ListRow · StatCard · SectionHeader · Pill · PriorityBadge
Inputs      TextField · SearchField
State       EmptyState · Spinner · Skeleton · ToastHost
Layout      FlowLayout · scroll_area · vbox / hbox helpers · CoverImage
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from PySide6.QtCore import (Qt, QSize, QRect, QPoint, QTimer, Signal, QVariantAnimation,
                            QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QEvent)
from PySide6.QtGui import (QFont, QPixmap, QPainter, QPainterPath, QColor, QAction,
                           QCursor, QPen)
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QLineEdit, QHBoxLayout,
                               QVBoxLayout, QLayout, QScrollArea, QSizePolicy, QGraphicsOpacityEffect,
                               QLayoutItem, QStyle, QAbstractButton)

from ui import icons, theme
from ui.theme import C, SP, R, FS, PRIORITY, PRIORITY_DIM, DURATION, font, repolish


# ── Layout helpers ─────────────────────────────────────────────────────────────

def vbox(parent=None, margins=(0, 0, 0, 0), spacing=SP["sm"]) -> QVBoxLayout:
    l = QVBoxLayout(parent) if parent is not None else QVBoxLayout()
    l.setContentsMargins(*margins)
    l.setSpacing(spacing)
    return l


def hbox(parent=None, margins=(0, 0, 0, 0), spacing=SP["sm"]) -> QHBoxLayout:
    l = QHBoxLayout(parent) if parent is not None else QHBoxLayout()
    l.setContentsMargins(*margins)
    l.setSpacing(spacing)
    return l


def scroll_area(content: QWidget, horizontal: bool = False) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded if horizontal else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sa.setWidget(content)
    return sa


class FlowLayout(QLayout):
    """Wraps children onto new rows as the width changes (responsive grids)."""

    def __init__(self, parent=None, h_space: int = SP["md"], v_space: int = SP["md"]):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h, self._v = h_space, v_space
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):            self._items.append(item)
    def count(self):                    return len(self._items)
    def itemAt(self, i):                return self._items[i] if 0 <= i < len(self._items) else None
    def takeAt(self, i):                return self._items.pop(i) if 0 <= i < len(self._items) else None
    def expandingDirections(self):      return Qt.Orientation(0)
    def hasHeightForWidth(self):        return True
    def heightForWidth(self, w):        return self._do_layout(QRect(0, 0, w, 0), True)
    def sizeHint(self):                 return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def clear(self):
        while self._items:
            it = self._items.pop()
            if it.widget():
                it.widget().deleteLater()

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        x, y = rect.x() + m.left(), rect.y() + m.top()
        right = rect.right() - m.right()
        line_h = 0
        for it in self._items:
            w = it.sizeHint().width()
            h = it.sizeHint().height()
            if x + w > right and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + self._v
                line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x += w + self._h
            line_h = max(line_h, h)
        return y + line_h + m.bottom() - rect.y()


# ── Text ───────────────────────────────────────────────────────────────────────

def label(text: str = "", role: str = "body", *, color: Optional[str] = None,
          size: Optional[str] = None, weight: Optional[int] = None, family: Optional[str] = None,
          align=None, wrap: bool = False, elide: bool = False, strike: bool = False) -> QLabel:
    """
    role: title · h2 · body · dim · muted · eyebrow · mono · value
    Extra overrides win over the role (size/weight/family/color).
    """
    l = ElidedLabel(text, role) if elide else QLabel(text)
    l.setProperty("role", role)
    # The global QSS sets font-family on every widget and wins over setFont(),
    # so overrides are applied as inline QSS too.
    css = []
    if size or weight or family:
        fam = family or ("mono" if role in ("eyebrow", "mono", "value") else "sans")
        fam_name = {"sans": theme.sans(), "mono": theme.mono(), "display": theme.display()}[fam]
        sz = size or {"title": "xl", "h2": "lg", "muted": "sm", "eyebrow": "2xs",
                      "value": "2xl"}.get(role, "base")
        css.append(f"font-family: '{fam_name}'; font-size: {theme._px(FS[sz])}px;")
        if weight:
            css.append(f"font-weight: {int(weight)};")
        l.setFont(font(sz, weight or QFont.Weight.Normal, fam))
    if strike:
        css.append("text-decoration: line-through;")
    if color:
        css.append(f"color: {color};")
    if css:
        l.setStyleSheet(" ".join(css))
    if align is not None:
        l.setAlignment(align)
    l.setWordWrap(wrap)
    return l


class ElidedLabel(QLabel):
    """Single-line label that elides with … instead of being cut off."""
    def __init__(self, text: str = "", role: str = "body", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, t: str):
        self._full = t
        super().setText(t)
        self._elide()

    def text(self): return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight, max(10, self.width())))
        self.setToolTip(self._full if fm.horizontalAdvance(self._full) > self.width() else "")


def Eyebrow(text: str) -> QLabel:
    return label(text.upper(), "eyebrow")


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "divider")
        self.setFixedHeight(1)


# ── Buttons ────────────────────────────────────────────────────────────────────

_ICON_COLOR = {"primary": C["on_accent"], "success": C["on_accent"], "danger": C["red"],
               "ghost": C["text_2"], "link": C["accent"], "default": C["text"], "nav": C["text_dim"],
               "chip": C["text_dim"], "seg": C["text_dim"], "icon": C["text_2"]}


class Button(QPushButton):
    """variant: default · primary · success · danger · ghost · link"""

    def __init__(self, text: str = "", variant: str = "default", icon: Optional[str] = None,
                 on_click: Optional[Callable] = None, parent=None, icon_size: int = 15):
        super().__init__(text, parent)
        self._variant, self._icon_name, self._icon_size = variant, icon, icon_size
        self.setProperty("variant", variant)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if icon:
            self.set_icon(icon)
        if on_click:
            self.clicked.connect(on_click)

    def set_icon(self, name: str, color: Optional[str] = None):
        self._icon_name = name
        self.setIcon(icons.icon(name, color or _ICON_COLOR.get(self._variant, C["text"]), self._icon_size))
        self.setIconSize(QSize(self._icon_size, self._icon_size))

    def set_loading(self, loading: bool, text: Optional[str] = None):
        """Disable + show a spinner icon while a background job runs."""
        self.setEnabled(not loading)
        if loading:
            self._saved = (self.text(), self._icon_name)
            if text is not None:
                self.setText(text)
            self.set_icon("loader-circle")
        elif getattr(self, "_saved", None):
            t, ic = self._saved
            self.setText(t)
            if ic:
                self.set_icon(ic)
            else:
                self.setIcon(icons.QIcon())
            self._saved = None


class IconButton(QPushButton):
    """Square icon-only button (needs a tooltip for accessibility)."""

    def __init__(self, icon: str, tooltip: str = "", size: int = 16, color: Optional[str] = None,
                 on_click: Optional[Callable] = None, checkable: bool = False, parent=None):
        super().__init__(parent)
        self._icon_name, self._size, self._color = icon, size, color
        self.setProperty("variant", "icon")
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setCheckable(checkable)
        self.setFixedSize(size + 16, size + 16)
        self.set_icon(icon, color)
        if on_click:
            self.clicked.connect(on_click)

    def set_icon(self, name: str, color: Optional[str] = None):
        self._icon_name = name
        self.setIcon(icons.icon(name, color or C["text_2"], self._size))
        self.setIconSize(QSize(self._size, self._size))

    def set_loading(self, loading: bool):
        self.setEnabled(not loading)
        if loading:
            self._saved_icon = self._icon_name
            self.set_icon("loader-circle", self._color)
        elif getattr(self, "_saved_icon", None):
            self.set_icon(self._saved_icon, self._color)
            self._saved_icon = None


class Segmented(QFrame):
    """iOS-style segmented control. options: [(key, label), …]"""
    changed = Signal(str)

    def __init__(self, options: Iterable[tuple[str, str]], current: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "seg")
        self._btns: dict[str, QPushButton] = {}
        lay = hbox(self, (3, 3, 3, 3), 2)
        for key, text in options:
            b = QPushButton(text)
            b.setProperty("variant", "seg")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, k=key: self.set_current(k))
            lay.addWidget(b)
            self._btns[key] = b
        self._current = None
        self.set_current(current or next(iter(self._btns), None), emit=False)

    def current(self) -> Optional[str]:
        return self._current

    def set_current(self, key: Optional[str], emit: bool = True):
        if key is None or key == self._current:
            return
        self._current = key
        for k, b in self._btns.items():
            b.setProperty("active", "true" if k == key else "false")
            repolish(b)
        if emit:
            self.changed.emit(key)

    def set_label(self, key: str, text: str):
        if key in self._btns:
            self._btns[key].setText(text)


class ChipGroup(QWidget):
    """Row of pill filters (single selection)."""
    changed = Signal(str)

    def __init__(self, options: Iterable[tuple[str, str]], current: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._btns: dict[str, QPushButton] = {}
        lay = hbox(self, spacing=SP["xs"])
        for key, text in options:
            b = QPushButton(text)
            b.setProperty("variant", "chip")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda _=False, k=key: self.set_current(k))
            lay.addWidget(b)
            self._btns[key] = b
        lay.addStretch()
        self._current = None
        self.set_current(current or next(iter(self._btns), None), emit=False)

    def current(self): return self._current

    def set_current(self, key, emit=True):
        if key is None or key == self._current:
            return
        self._current = key
        for k, b in self._btns.items():
            b.setProperty("active", "true" if k == key else "false")
            repolish(b)
        if emit:
            self.changed.emit(key)

    def set_label(self, key: str, text: str):
        if key in self._btns:
            self._btns[key].setText(text)


# ── Surfaces ───────────────────────────────────────────────────────────────────

class Card(QFrame):
    """Elevated surface. clickable=True → emits clicked and shows hover."""
    clicked = Signal()

    def __init__(self, parent=None, padding: int = SP["lg"], clickable: bool = False,
                 spacing: int = SP["sm"]):
        super().__init__(parent)
        self.setProperty("surface", "card")
        self.setProperty("hoverable", "true" if clickable else "false")
        self._clickable = clickable
        if clickable:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.body = vbox(self, (padding, padding, padding, padding), spacing)

    def mouseReleaseEvent(self, e):
        if self._clickable and e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.pos()):
            child = self.childAt(e.pos())
            while child is not None and child is not self:
                if isinstance(child, QAbstractButton):
                    child = None
                    break
                child = child.parentWidget()
            if child is not None:
                self.clicked.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if self._clickable and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Space):
            self.clicked.emit()
        super().keyPressEvent(e)


class ListRow(Card):
    """A horizontal, clickable row: [leading] title/subtitle …stretch… [trailing]."""

    def __init__(self, title: str, subtitle: str = "", leading: Optional[QWidget] = None,
                 trailing: Optional[QWidget] = None, clickable: bool = True, parent=None):
        super().__init__(parent, padding=SP["md"], clickable=clickable, spacing=0)
        self.setProperty("surface", "card")
        row = hbox(spacing=SP["md"])
        self.body.addLayout(row)
        if leading is not None:
            row.addWidget(leading, 0, Qt.AlignmentFlag.AlignVCenter)
        col = vbox(spacing=2)
        self.title = ElidedLabel(title, "body")
        self.title.setFont(font("base", QFont.Weight.Medium))
        col.addWidget(self.title)
        self.subtitle = ElidedLabel(subtitle, "muted")
        self.subtitle.setVisible(bool(subtitle))
        col.addWidget(self.subtitle)
        row.addLayout(col, 1)
        self.trailing_box = hbox(spacing=SP["sm"])
        if trailing is not None:
            self.trailing_box.addWidget(trailing)
        row.addLayout(self.trailing_box)

    def set_selected(self, selected: bool):
        self.setProperty("active", "true" if selected else "false")
        repolish(self)


class Pill(QLabel):
    """Small rounded badge. tone: accent · green · gold · red · violet · neutral · custom hex"""

    def __init__(self, text: str = "", tone: str = "neutral", parent=None, mono: bool = True):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._mono = mono
        self.setFont(font("2xs", QFont.Weight.Bold, "mono" if mono else "sans", 0.5))
        self.set_tone(tone)

    def set_tone(self, tone: str):
        fg, bg = {
            "accent":  (C["accent"], C["accent_dim"]),
            "green":   (C["green"],  C["green_dim"]),
            "gold":    (C["gold"],   C["gold_dim"]),
            "red":     (C["red"],    C["red_dim"]),
            "violet":  (C["violet"], "#221a3d"),
            "neutral": (C["text_dim"], C["surface_3"]),
            "solid":   (C["on_accent"], C["text"]),
        }.get(tone, (tone, C["surface_3"]))
        fam = theme.mono() if self._mono else theme.sans()
        self.setStyleSheet(f"color:{fg}; background:{bg}; border-radius:{R['sm']}px; padding: 2px 7px; "
                           f"font-family:'{fam}'; font-size:{theme._px(FS['2xs'])}px; font-weight:700;")


class PriorityBadge(Pill):
    def __init__(self, priority: str = "C", parent=None):
        super().__init__(priority, parent=parent)
        self.set_priority(priority)

    def set_priority(self, p: str):
        self.setText(p)
        self.setStyleSheet(f"color:{PRIORITY.get(p, C['text_dim'])}; background:{PRIORITY_DIM.get(p, C['surface_3'])};"
                           f" border-radius:{R['sm']}px; padding: 2px 8px; min-width: 12px;")


class StatCard(Card):
    """Metric tile: eyebrow label, big mono value, optional caption + icon."""

    def __init__(self, title: str, value: str = "—", icon: Optional[str] = None,
                 tone: str = "accent", caption: str = "", parent=None):
        super().__init__(parent, padding=SP["lg"], spacing=SP["xs"])
        color = {"accent": C["accent"], "green": C["green"], "gold": C["gold"], "red": C["red"],
                 "violet": C["violet"], "cyan": C["cyan"], "pink": C["pink"], "orange": C["orange"]}.get(tone, tone)
        top = hbox(spacing=SP["sm"])
        self._icon = QLabel()
        if icon:
            self._icon.setPixmap(icons.pixmap(icon, color, 16))
            top.addWidget(self._icon)
        self._title = label(title.upper(), "eyebrow", elide=True)
        top.addWidget(self._title, 1)
        self.body.addLayout(top)
        self._value = label(value, "value", color=color)
        self.body.addWidget(self._value)
        self._caption = label(caption, "muted", elide=True)
        self._caption.setVisible(bool(caption))
        self.body.addWidget(self._caption)
        self.setMinimumWidth(150)
        self._anim: Optional[QVariantAnimation] = None

    def set_value(self, value, fmt: Callable[[float], str] = None, animate: bool = True):
        """Numbers count up smoothly; strings are set directly."""
        if isinstance(value, (int, float)) and animate:
            fmt = fmt or (lambda v: f"{v:,.0f}")
            start = getattr(self, "_num", 0.0)
            self._num = float(value)
            if self._anim:
                self._anim.stop()
            if float(start) == float(value):
                self._value.setText(fmt(float(value)))
                return
            a = QVariantAnimation(self)
            a.setStartValue(float(start)); a.setEndValue(float(value))
            a.setDuration(DURATION["slow"]); a.setEasingCurve(QEasingCurve.Type.OutCubic)
            a.valueChanged.connect(lambda v: self._value.setText(fmt(v)))
            a.start()
            self._anim = a
        else:
            self._value.setText(str(value) if fmt is None else fmt(value))

    def set_caption(self, text: str):
        self._caption.setText(text)
        self._caption.setVisible(bool(text))

    def set_title(self, text: str):
        self._title.setText(text.upper())


class SectionHeader(QWidget):
    """The 56 px view header: title (+ subtitle) on the left, actions right."""

    def __init__(self, title: str, subtitle: str = "", actions: Iterable[QWidget] = (), parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        lay = hbox(self, (0, 0, 0, 0), SP["md"])
        col = vbox(spacing=0)
        self.title = label(title, "title")
        col.addWidget(self.title)
        self.subtitle = label(subtitle, "muted")
        self.subtitle.setVisible(bool(subtitle))
        col.addWidget(self.subtitle)
        lay.addLayout(col)
        lay.addStretch()
        self.actions = hbox(spacing=SP["sm"])
        for a in actions:
            self.actions.addWidget(a)
        lay.addLayout(self.actions)


class SubHeader(QWidget):
    """In-content section title with optional right-side widget."""
    def __init__(self, title: str, trailing: Optional[QWidget] = None, parent=None):
        super().__init__(parent)
        lay = hbox(self, (0, SP["md"], 0, SP["xs"]))
        self.title = label(title, "h2")
        lay.addWidget(self.title)
        lay.addStretch()
        if trailing:
            lay.addWidget(trailing)


# ── Inputs ─────────────────────────────────────────────────────────────────────

class TextField(QLineEdit):
    def __init__(self, placeholder: str = "", icon: Optional[str] = None, password: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(34)
        if icon:
            self.addAction(icons.icon(icon, C["text_dim"], 14), QLineEdit.ActionPosition.LeadingPosition)
        if password:
            self.setEchoMode(QLineEdit.EchoMode.Password)
            self._eye = QAction(icons.icon("eye", C["text_dim"], 14), "", self)
            self._eye.triggered.connect(self._toggle_echo)
            self.addAction(self._eye, QLineEdit.ActionPosition.TrailingPosition)

    def _toggle_echo(self):
        hidden = self.echoMode() == QLineEdit.EchoMode.Password
        self.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self._eye.setIcon(icons.icon("eye-off" if hidden else "eye", C["text_dim"], 14))

    def set_error(self, error: bool):
        self.setProperty("error", "true" if error else "false")
        repolish(self)


def SearchField(placeholder: str = "Search…", parent=None) -> TextField:
    f = TextField(placeholder, icon="search", parent=parent)
    f.setClearButtonEnabled(True)
    return f


# ── State ──────────────────────────────────────────────────────────────────────

class EmptyState(QWidget):
    def __init__(self, icon: str, title: str, subtitle: str = "", action: Optional[QWidget] = None,
                 parent=None):
        super().__init__(parent)
        lay = vbox(self, (SP["xl"],) * 4, SP["sm"])
        lay.addStretch()
        ic = QLabel(); ic.setPixmap(icons.pixmap(icon, C["text_muted"], 40, 1.25))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        self.title = label(title, "h2", align=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title)
        self.subtitle = label(subtitle, "dim", align=Qt.AlignmentFlag.AlignCenter, wrap=True)
        self.subtitle.setVisible(bool(subtitle))
        lay.addWidget(self.subtitle)
        if action:
            row = hbox(); row.addStretch(); row.addWidget(action); row.addStretch()
            lay.addSpacing(SP["sm"]); lay.addLayout(row)
        lay.addStretch()


class Spinner(QWidget):
    """Rotating loader ring (Lucide loader-circle)."""
    def __init__(self, size: int = 18, color: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._size, self._color = size, color or C["accent"]
        self._angle = 0
        self.setFixedSize(size, size)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0); self._anim.setEndValue(360)
        self._anim.setDuration(900); self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._tick)

    def _tick(self, v):
        self._angle = v
        self.update()

    def showEvent(self, e):
        self._anim.start(); super().showEvent(e)

    def hideEvent(self, e):
        self._anim.stop(); super().hideEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self._size / 2, self._size / 2)
        p.rotate(self._angle)
        pm = icons.pixmap("loader-circle", self._color, self._size)
        p.drawPixmap(-self._size // 2, -self._size // 2, self._size, self._size, pm)


class Skeleton(QFrame):
    """Shimmering placeholder block while content loads."""
    def __init__(self, w: int = 120, h: int = 14, radius: int = R["sm"], parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self._radius = radius
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0); self._anim.setEndValue(1.0)
        self._anim.setDuration(1200); self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._tick)

    def _tick(self, v):
        self._t = v; self.update()

    def showEvent(self, e): self._anim.start(); super().showEvent(e)
    def hideEvent(self, e): self._anim.stop(); super().hideEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath(); path.addRoundedRect(0, 0, self.width(), self.height(), self._radius, self._radius)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor(C["surface_3"]))
        x = int((self._t * 2 - 0.5) * self.width())
        from PySide6.QtGui import QLinearGradient
        g = QLinearGradient(x - 60, 0, x + 60, 0)
        g.setColorAt(0, QColor(0, 0, 0, 0)); g.setColorAt(0.5, QColor(255, 255, 255, 18)); g.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), g)


class Toast(QFrame):
    def __init__(self, message: str, tone: str, parent):
        super().__init__(parent)
        self.setProperty("surface", "card")
        color = {"success": C["green"], "error": C["red"], "warning": C["gold"], "info": C["accent"]}[tone]
        icon_name = {"success": "circle-check", "error": "circle-x", "warning": "triangle-alert", "info": "info"}[tone]
        lay = hbox(self, (SP["md"], SP["sm"], SP["lg"], SP["sm"]), SP["sm"])
        ic = QLabel(); ic.setPixmap(icons.pixmap(icon_name, color, 16))
        lay.addWidget(ic)
        lbl = label(message, "body", wrap=len(message) > 56)
        lbl.setMaximumWidth(420)
        lay.addWidget(lbl)
        self.setStyleSheet(f"QFrame {{ background: {C['surface_3']}; border: 1px solid {C['border_strong']}; border-radius: {R['md']}px; }}")
        self.adjustSize()


class ToastHost:
    """Bottom-right stacked notifications. host = ToastHost(main_window); host.show('Saved', 'success')"""

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._toasts: list[Toast] = []

    def show(self, message: str, tone: str = "info", duration_ms: int = 3200):
        t = Toast(message, tone, self._parent)
        self._toasts.append(t)
        self._place()
        t.show()
        eff = QGraphicsOpacityEffect(t); t.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", t); a.setStartValue(0.0); a.setEndValue(1.0)
        a.setDuration(DURATION["base"]); a.start()
        QTimer.singleShot(duration_ms, lambda: self._dismiss(t))

    def _dismiss(self, t: Toast):
        if t not in self._toasts:
            return
        eff = t.graphicsEffect()
        a = QPropertyAnimation(eff, b"opacity", t); a.setStartValue(1.0); a.setEndValue(0.0)
        a.setDuration(DURATION["base"])

        def _done():
            if t in self._toasts:
                self._toasts.remove(t)
            t.deleteLater()
            self._place()
        a.finished.connect(_done)
        a.start()

    def _place(self):
        pw, ph = self._parent.width(), self._parent.height()
        y = ph - SP["xl"]
        for t in reversed(self._toasts):
            t.adjustSize()
            y -= t.height()
            t.move(pw - t.width() - SP["xl"], y)
            y -= SP["sm"]

    def relayout(self):
        self._place()


# ── Images ─────────────────────────────────────────────────────────────────────

class CoverImage(QLabel):
    """Rounded cover with a placeholder; keeps aspect via scaled pixmap."""
    def __init__(self, w: int, h: int, radius: int = R["md"], parent=None):
        super().__init__(parent)
        self._w, self._h, self._radius = w, h, radius
        self.setFixedSize(w, h)
        self._src: Optional[QPixmap] = None
        self.set_pixmap(None)

    def set_pixmap(self, pm: Optional[QPixmap]):
        self._src = pm
        out = QPixmap(self._w, self._h)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath(); path.addRoundedRect(0, 0, self._w, self._h, self._radius, self._radius)
        p.setClipPath(path)
        if pm and not pm.isNull():
            scaled = pm.scaled(self._w, self._h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self._w - scaled.width()) // 2, (self._h - scaled.height()) // 2, scaled)
        else:
            p.fillRect(out.rect(), QColor(C["surface_3"]))
            ic = icons.pixmap("image", C["text_muted"], min(28, self._w // 3))
            p.drawPixmap((self._w - min(28, self._w // 3)) // 2, (self._h - min(28, self._w // 3)) // 2,
                         min(28, self._w // 3), min(28, self._w // 3), ic)
        p.setPen(QPen(QColor(255, 255, 255, 14), 1))
        p.drawPath(path)
        p.end()
        self.setPixmap(out)
