import threading
from datetime import datetime

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRect
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor

from config import COLORS, STEAM_SALE_EVENTS, PRIORITY_COLORS
import data.repository as repo
import services.steam_api as steam
import i18n
from ui.settings_loader import get_settings
from ui.event_time import (event_start_dt, event_end_dt,
                           event_state, visible_events,
                           hero_event as _hero_event,
                           parse_gmt_offset)


def _lbl(text, size=11, bold=False, color=None):
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold: f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or COLORS['text']}; background-color:transparent;")
    return l


def _load_image_bg(url_or_path: str, w: int, h: int) -> "QPixmap | None":
    """Load an image from file path or URL, crop to w×h."""
    from pathlib import Path
    px = QPixmap()
    if url_or_path and Path(url_or_path).exists():
        px.load(url_or_path)
    elif url_or_path and url_or_path.startswith("http"):
        try:
            import urllib.request, ssl, certifi
            from PySide6.QtCore import QByteArray
            ctx = ssl.create_default_context(cafile=certifi.where())
            req = urllib.request.Request(url_or_path,
                                         headers={"User-Agent": "SteamCurator/2.0"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                px.loadFromData(QByteArray(r.read()))
        except Exception as e:
            print(f"[Deals] image fetch error: {e}")
            return None
    if px.isNull():
        return None
    scaled = px.scaled(w, h,
                       Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
    xo = max(0, (scaled.width()  - w) // 2)
    yo = max(0, (scaled.height() - h) // 2)
    return scaled.copy(QRect(xo, yo, w, h))


def _darken(px: QPixmap, alpha: int = 120) -> QPixmap:
    """Overlay a dark layer on a pixmap for text readability."""
    result = px.copy()
    p = QPainter(result)
    p.fillRect(result.rect(), QColor(0, 0, 0, alpha))
    p.end()
    return result


class _Sig(QObject):
    refresh_done  = Signal(int)
    status_update = Signal(str, str)
    image_ready   = Signal(object, object, int, int, int)  # lbl, px, w, h, token


class _ImageFrame(QFrame):
    """
    QFrame that loads a sale image as background on first resizeEvent.
    Uses a Signal to update the widget from the main thread safely.
    """
    def __init__(self, event: dict, bg_label: QLabel,
                 darken_alpha: int = 90, sig=None, parent=None):
        super().__init__(parent)
        self._event        = event
        self._bg_label     = bg_label
        self._darken_alpha = darken_alpha
        self._sig          = sig
        self._loaded       = False
        self._loading      = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            return

        # Resize all absolute-positioned children to fill the new size
        for child in self.findChildren(QLabel) + self.findChildren(QWidget):
            if child is not self and child.parent() is self:
                try:
                    child.setGeometry(0, 0, w, h)
                except RuntimeError:
                    pass

        # Reload image if:
        #   a) never loaded yet, OR
        #   b) loaded at a much smaller width (e.g. layout gave us 0 or a tiny
        #      size on first pass, then expanded to the real width later).
        loaded_w = getattr(self, "_loaded_w", 0)
        needs_reload = not self._loaded or (w > loaded_w * 1.2 and w > 50)

        if not needs_reload:
            return
        if self._loading:
            return

        self._loading = True
        self._loaded  = True
        self._loaded_w = w   # remember the width we loaded at

        event, lbl, alpha, sig = self._event, self._bg_label, self._darken_alpha, self._sig
        tok = getattr(self, "_token", -1)

        def _worker():
            _load_and_apply_image(event, lbl, w, h, alpha, sig, token=tok)

        self._loading = False   # allow reload on next significant resize
        threading.Thread(target=_worker, daemon=True).start()


def _load_and_apply_image(event: dict, lbl: QLabel,
                          w: int, h: int, alpha: int, sig=None,
                          token: int = -1):
    """Worker: loads image from cache and applies it via signal to main thread."""
    from services.sale_images import get_local_path
    import time
    key = event.get("server_img", event.get("key", ""))

    # Wait up to 20s for the image to appear in cache
    deadline = time.time() + 20
    path = None
    while time.time() < deadline:
        path = get_local_path(key)
        if path:
            break
        time.sleep(0.3)

    if not path:
        return

    px = _load_image_bg(str(path), w, h)
    if not px:
        return
    px = _darken(px, alpha)

    # Use signal to update widget in main thread — QTimer.singleShot from
    # secondary threads can fail silently in PySide6
    if sig is not None:
        try:
            sig.image_ready.emit(lbl, px, w, h, token)
        except RuntimeError:
            pass


class DealsView(QFrame):

    def __init__(self, parent=None, on_game_click=None, **kwargs):
        super().__init__(parent)
        self.on_game_click = on_game_click
        self._refreshing   = False
        self._sig          = _Sig()
        self._sig.refresh_done.connect(self._on_refresh_done)
        self._sig.status_update.connect(self._set_status)
        self._render_token = 0   # incremented on each refresh; async workers check this before applying images
        self._sig.image_ready.connect(self._apply_image)
        self.setStyleSheet(f"background:{COLORS['bg']};")
        self._countdown_timer = QTimer()
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(52)
        hdr.setStyleSheet(f"background:{COLORS['panel']};")
        hb = QHBoxLayout(hdr)
        hb.setContentsMargins(18, 0, 18, 0)
        hb.addWidget(_lbl(i18n.t("deals.title"), 16, bold=True))
        hb.addStretch()
        self._status_lbl = _lbl("", 11, color=COLORS["green"])
        hb.addWidget(self._status_lbl)
        self._refresh_btn = QPushButton(i18n.t("deals.refresh_all"))
        self._refresh_btn.setFixedSize(210, 32)
        self._refresh_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{COLORS['text_dim']};
                border:1px solid {COLORS['border']}; border-radius:6px;
                font-family:'Space Mono'; font-size:11px; }}
            QPushButton:hover {{ background:{COLORS['card_hover']}; }}
        """)
        self._refresh_btn.clicked.connect(self._refresh_all_prices)
        hb.addWidget(self._refresh_btn)
        root.addWidget(hdr)

        # Scroll area
        self._content = QWidget()
        self._content.setStyleSheet(f"background:{COLORS['bg']};")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(16, 14, 16, 16)
        self._content_lay.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._content)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border:none; background:{COLORS['bg']}; }}
            QScrollBar:vertical {{ background:{COLORS['bg']}; width:6px; border:none; }}
            QScrollBar::handle:vertical {{ background:{COLORS['border']}; border-radius:3px; min-height:30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        root.addWidget(scroll, 1)
        self.refresh()

    def hideEvent(self, e):
        self._countdown_timer.stop()
        super().hideEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        if hasattr(self, "_countdown_lbl"):
            self._countdown_timer.start()

    def _set_status(self, text, color):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(f"color:{color}; background-color:transparent;")

    def _apply_image(self, lbl, px, w, h, token: int = -1):
        """Called from main thread via signal — safe to update widget.

        token: the _render_token at the time the worker was launched.
        If the token has changed (user navigated away and back), discard.
        """
        if token != -1 and token != self._render_token:
            return   # stale image from a previous refresh cycle
        try:
            if not lbl.isVisible() and not self.isVisible():
                return
            lbl.setPixmap(px)
            # Use actual parent width instead of 9999
            parent = lbl.parent()
            actual_w = parent.width() if parent else w
            lbl.setGeometry(0, 0, max(actual_w, w), h)
            lbl.lower()
        except RuntimeError:
            pass

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self):
        self._render_token += 1   # invalidate any in-flight image workers
        self._countdown_timer.stop()
        # Use deleteLater for every widget — prevents zombie widgets
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.deleteLater()
        self._render_hero()
        self._render_sale_cards()
        self._render_on_sale()
        self._content_lay.addStretch()

    # ── Sale events source ───────────────────────────────────────────────────

    def _get_sale_events(self) -> list:
        """
        Return sale events from the server JSON when available.
        Falls back to config.STEAM_SALE_EVENTS so the UI always has data.
        """
        from services.sale_images import get_sale_events
        events = get_sale_events()
        if events:
            return events
        print("[DealsView] Falling back to config.STEAM_SALE_EVENTS")
        return STEAM_SALE_EVENTS

    # ── Hero ──────────────────────────────────────────────────────────────────

    def _render_hero(self):
        user_tz = get_settings().get("timezone", "GMT-6")
        all_ev  = self._get_sale_events()
        vis     = visible_events(all_ev, user_tz)
        if not vis:
            return

        # Hero: BANNER_FEATURED if present and not expired, else first visible.
        event = _hero_event(all_ev, user_tz)
        if not event:
            return

        state, target = event_state(event, user_tz)
        is_active = state == "active"
        name      = event.get("name") or i18n.t(f"sale_events.{event['key']}")
        color     = event["color_top"]

        # Store timezone for countdown calculations
        self._hero_tz = parse_gmt_offset(user_tz)

        # ── Outer container, fixed height ─────────────────────────────────────
        hero_bg_lbl = QLabel()   # created before hero so we can pass it
        hero_bg_lbl.setStyleSheet("background:transparent;")

        hero = _ImageFrame(event, hero_bg_lbl, darken_alpha=60, sig=self._sig)
        hero._token = self._render_token
        hero.setFixedHeight(210)
        hero.setObjectName("HeroFrame")
        hero.setStyleSheet(f"""
            QFrame#HeroFrame {{
                background:{color};
                border-radius:12px;
                margin-bottom:10px;
            }}
        """)

        # Background image label — absolute, behind everything
        hero_bg_lbl.setParent(hero)
        hero_bg_lbl.setGeometry(0, 0, max(hero.width(), 800), 210)
        hero_bg_lbl.lower()

        # Dark gradient overlay for readability — use layout to fill parent
        overlay = QLabel(hero)
        overlay.setGeometry(0, 0, max(hero.width(), 800), 210)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.setStyleSheet("""
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0   rgba(0,0,0,0.82),
                stop:0.55 rgba(0,0,0,0.45),
                stop:1   rgba(0,0,0,0.05)
            );
            border-radius:12px;
        """)

        # Content layer — use a proper layout inside the frame
        content = QWidget(hero)
        content.setGeometry(0, 0, max(hero.width(), 800), 210)
        content.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        content.setStyleSheet("background-color:transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(28, 18, 28, 18)
        cl.setSpacing(4)

        # Status badge — mirrors the same tri-state logic as the small cards
        _confirmed = event.get("confirmed", False)
        badge_text  = ("🟢  ACTIVE NOW"   if is_active
                       else "✅  COMING SOON" if _confirmed
                       else "⏳  ESTIMATED")
        badge_color = (COLORS["green"] if is_active
                       else COLORS["blue"] if _confirmed
                       else COLORS["gold"])
        badge = QLabel(badge_text)
        badge.setFont(QFont("Space Mono", 9, QFont.Weight.Bold))
        badge.setStyleSheet(f"color:{badge_color}; background-color:transparent;")
        cl.addWidget(badge)

        # Sale name
        title = QLabel(name)
        title.setFont(QFont("Space Mono", 24, QFont.Weight.Bold))
        title.setStyleSheet("color:#ffffff; background-color:transparent;")
        cl.addWidget(title)

        # Countdown
        prefix_lbl = QLabel(
            i18n.t("deals.ends_in_label") if is_active
            else i18n.t("deals.starts_in_label"))
        prefix_lbl.setFont(QFont("Space Mono", 11))
        prefix_lbl.setStyleSheet(f"color:rgba(255,255,255,0.65); background-color:transparent;")
        cl.addWidget(prefix_lbl)

        self._hero_target = target   # tz-aware datetime from event_state
        self._countdown_lbl = QLabel()
        self._countdown_lbl.setFont(QFont("Space Mono", 30, QFont.Weight.Bold))
        self._countdown_lbl.setStyleSheet(f"color:{color}; background-color:transparent;")
        cl.addWidget(self._countdown_lbl)

        # Bottom row
        bot = QHBoxLayout()
        dates_lbl = QLabel(f"{event['start']}  →  {event['end']}")
        dates_lbl.setFont(QFont("Space Mono", 10))
        dates_lbl.setStyleSheet("color:rgba(255,255,255,0.55); background-color:transparent;")
        bot.addWidget(dates_lbl)
        bot.addStretch()
        import data.repository as _r
        n = len(_r.get_on_sale())
        if n > 0:
            sale_lbl = QLabel(f"⚡  {n} game{'s' if n != 1 else ''} from your wishlist on sale right now")
            sale_lbl.setFont(QFont("Space Mono", 10, QFont.Weight.Bold))
            sale_lbl.setStyleSheet(f"color:{COLORS['green']}; background-color:transparent;")
            bot.addWidget(sale_lbl)
        cl.addLayout(bot)

        self._content_lay.addWidget(hero)
        self._tick_countdown()
        self._countdown_timer.start()

    # ── Countdown ─────────────────────────────────────────────────────────────

    def _tick_countdown(self):
        if not hasattr(self, "_countdown_lbl") or not hasattr(self, "_hero_target"):
            return
        try:
            tz    = getattr(self, "_hero_tz", parse_gmt_offset("GMT-6"))
            delta = self._hero_target - datetime.now(tz)
            total = int(delta.total_seconds())
            if total <= 0:
                self._countdown_lbl.setText("NOW!")
                self._countdown_timer.stop()
                return
            d = total // 86400
            h = (total % 86400) // 3600
            m = (total % 3600) // 60
            s = total % 60
            if d > 0:
                self._countdown_lbl.setText(f"{d}d  {h:02d}h  {m:02d}m  {s:02d}s")
            else:
                self._countdown_lbl.setText(f"{h:02d}h  {m:02d}m  {s:02d}s")
        except Exception:
            pass

    # ── Sale cards ────────────────────────────────────────────────────────────

    def _render_sale_cards(self):
        self._content_lay.addWidget(
            _lbl(i18n.t("deals.upcoming"), 13, bold=True, color=COLORS["text_dim"]))

        user_tz = get_settings().get("timezone", "GMT-6")
        # Preserve JSON order — just filter out expired events.
        # BANNER_FEATURED (hero) is included as card[0] per spec.
        events  = visible_events(self._get_sale_events(), user_tz)

        grid_w = QWidget()
        grid_w.setStyleSheet("background-color:transparent;")
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 8, 0, 16)
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        for idx, event in enumerate(events):
            card = self._make_sale_card(event)
            grid.addWidget(card, idx // 2, idx % 2)

        self._content_lay.addWidget(grid_w)

    def _make_sale_card(self, event: dict, today=None) -> QFrame:
        user_tz   = get_settings().get("timezone", "GMT-6")
        state, target = event_state(event, user_tz)
        is_active = state == "active"
        utz       = parse_gmt_offset(user_tz)
        now       = datetime.now(utz)
        start_dt  = event_start_dt(event).astimezone(utz)
        end_dt    = event_end_dt(event).astimezone(utz)
        days_to   = max(0, (start_dt - now).days) if not is_active else 0
        days_left = max(0, (end_dt   - now).days) if is_active else 0
        name      = event.get("name") or i18n.t(f"sale_events.{event['key']}")
        color     = event["color_top"]
        confirmed = event.get("confirmed", False)

        card_obj_name = f"SaleCard_{event['key']}"
        bg_lbl = QLabel()
        bg_lbl.setStyleSheet("background:transparent;")

        card = _ImageFrame(event, bg_lbl, darken_alpha=90, sig=self._sig)
        card._token = self._render_token
        card.setFixedHeight(88)
        card.setObjectName(card_obj_name)
        card.setStyleSheet(f"""
            QFrame#{card_obj_name} {{
                background:{color}44;
                border:{'2' if is_active else '1'}px solid {color if is_active else color + '55'};
                border-radius:10px;
            }}
        """)

        # BG image label — parented after card exists
        bg_lbl.setParent(card)
        bg_lbl.setGeometry(0, 0, max(card.width(), 600), 88)
        bg_lbl.lower()

        # Gradient overlay
        ov = QLabel(card)
        ov.setGeometry(0, 0, max(card.width(), 600), 88)
        ov.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        ov.setStyleSheet("""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 rgba(0,0,0,0.72),
                stop:0.65 rgba(0,0,0,0.35),
                stop:1 rgba(0,0,0,0));
            border-radius:9px;
        """)

        # Content
        cnt = QWidget(card)
        cnt.setGeometry(0, 0, max(card.width(), 600), 88)
        cnt.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        cnt.setStyleSheet("background-color:transparent;")
        cl = QHBoxLayout(cnt)
        cl.setContentsMargins(14, 8, 14, 8)

        left = QVBoxLayout()
        left.setSpacing(2)

        # Name row
        nr = QHBoxLayout(); nr.setSpacing(6)
        emoji_lbl = QLabel(event["emoji"])
        emoji_lbl.setFont(QFont("", 16))
        emoji_lbl.setStyleSheet("background-color:transparent;")
        nr.addWidget(emoji_lbl)
        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Space Mono", 12, QFont.Weight.Bold))
        name_lbl.setStyleSheet("color:#ffffff; background-color:transparent;")
        nr.addWidget(name_lbl, 1)

        badge_text  = (i18n.t("deals.active_now") if is_active
                       else i18n.t("deals.confirmed") if confirmed
                       else i18n.t("deals.estimated"))
        badge_bg    = (COLORS["green"] if is_active
                       else COLORS["blue"] if confirmed
                       else "rgba(255,255,255,0.15)")
        badge_fg    = "#000000" if is_active else "#ffffff"
        badge = QLabel(badge_text)
        badge.setFont(QFont("Space Mono", 8, QFont.Weight.Bold))
        badge.setStyleSheet(f"background:{badge_bg}; color:{badge_fg}; "
                            f"border-radius:4px; padding:1px 5px;")
        nr.addWidget(badge)
        left.addLayout(nr)

        # Dates + status
        status_text  = (i18n.t("deals.days_left",  n=days_left)  if is_active
                        else i18n.t("deals.starts_in", n=days_to))
        status_color = COLORS["green"] if is_active else "rgba(255,255,255,0.75)"
        dr = QHBoxLayout(); dr.setSpacing(0)
        dr.addWidget(_lbl(f"{event['start']}  →  {event['end']}", 9,
                          color="rgba(255,255,255,0.55)"))
        dr.addStretch()
        dr.addWidget(_lbl(status_text, 10, bold=True, color=status_color))
        left.addLayout(dr)
        cl.addLayout(left)

        return card

    # ── On-sale games ─────────────────────────────────────────────────────────

    def _render_on_sale(self):
        games    = repo.get_on_sale()
        currency = next((g.price.currency for g in games if g.price), "")

        hr = QWidget()
        hr.setStyleSheet("background-color:transparent;")
        hl = QHBoxLayout(hr)
        hl.setContentsMargins(0, 4, 0, 6)
        hl.addWidget(_lbl(i18n.t("deals.on_sale"), 13, bold=True,
                          color=COLORS["text_dim"]))
        hl.addStretch()
        if currency:
            hl.addWidget(_lbl(i18n.t("deals.currency_note", currency=currency),
                              10, color=COLORS["text_dim"]))
        self._content_lay.addWidget(hr)

        if not games:
            self._content_lay.addWidget(
                _lbl(i18n.t("deals.no_deals"), 13, color=COLORS["text_dim"]))
            return

        for game in sorted(games, key=lambda g: g.price_diff_pct or 999):
            self._content_lay.addWidget(self._make_game_row(game))

    def _make_game_row(self, game) -> QFrame:
        row = QFrame()
        row.setStyleSheet(f"""
            QFrame {{ background:{COLORS['card']};
                border:1px solid {COLORS['border']}; border-radius:8px;
                margin-bottom:3px; }}
            QFrame:hover {{ border-color:{COLORS['blue']}; }}
        """)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.mousePressEvent = lambda e: self.on_game_click(game) if self.on_game_click else None

        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 10, 14, 10)

        color = PRIORITY_COLORS.get(game.priority, "#666666")
        badge = QLabel(game.priority)
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFont(QFont("Space Mono", 10, QFont.Weight.Bold))
        badge.setStyleSheet(f"background:{color}; color:{'#1a0f00' if game.priority=='S' else '#ffffff'};"
                            f" border-radius:4px;")
        rl.addWidget(badge)

        info = QWidget()
        info.setStyleSheet("background-color:transparent;")
        il = QVBoxLayout(info)
        il.setContentsMargins(8, 0, 0, 0); il.setSpacing(1)
        il.addWidget(_lbl(game.name, 13, bold=True))
        genre = game.genre.split(",")[0] if game.genre else "—"
        il.addWidget(_lbl(f"{genre} · {game.release_year or '—'}", 11,
                          color=COLORS["text_dim"]))
        rl.addWidget(info, 1)

        if game.price:
            pw = QWidget(); pw.setStyleSheet("background-color:transparent;")
            pl = QHBoxLayout(pw); pl.setContentsMargins(0,0,0,0); pl.setSpacing(8)
            if game.price.discount_pct:
                d = QLabel(f"-{game.price.discount_pct}%")
                d.setFixedSize(50, 24); d.setAlignment(Qt.AlignmentFlag.AlignCenter)
                d.setFont(QFont("Space Mono", 11, QFont.Weight.Bold))
                d.setStyleSheet(f"background:{COLORS['green']}; color:#ffffff; border-radius:4px;")
                pl.addWidget(d)
            pl.addWidget(_lbl(f"${game.price.base:,.0f}", 11, color=COLORS["text_dim"]))
            pl.addWidget(_lbl(f"${game.price.current:,.0f} {game.price.currency}",
                              14, bold=True, color=COLORS["green"]))
            rl.addWidget(pw)

        return row

    # ── Price refresh ─────────────────────────────────────────────────────────

    def _refresh_all_prices(self):
        if self._refreshing: return
        self._refreshing = True
        self._refresh_btn.setEnabled(False)

        def _work():
            settings = get_settings()
            country  = settings.get("country", "mx")
            games    = repo.get_all()
            total    = len(games)
            for i, game in enumerate(games):
                self._sig.status_update.emit(
                    i18n.t("settings.refreshing", n=f"{i+1}/{total}"),
                    COLORS["blue"])
                new_price = steam.refresh_price(game.app_id, country=country)
                if new_price:
                    game.price = new_price
                    repo.update(game)
            self._sig.refresh_done.emit(total)

        threading.Thread(target=_work, daemon=True).start()

    def _on_refresh_done(self, total):
        self._refreshing = False
        self._refresh_btn.setEnabled(True)
        self._sig.status_update.emit(
            i18n.t("settings.refresh_done", n=total), COLORS["green"])
        QTimer.singleShot(4000, lambda: self._sig.status_update.emit("", COLORS["green"]))
        self.refresh()