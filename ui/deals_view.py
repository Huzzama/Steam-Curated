"""DealsView — PySide6."""
import threading
from datetime import datetime, date
from pathlib import Path

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QPixmap

from config import COLORS, STEAM_SALE_EVENTS, PRIORITY_COLORS
import data.repository as repo
import services.steam_api as steam
import i18n
from ui.settings_loader import get_settings

BAND_H = 70


def _lbl(text, size=11, bold=False, color=None):
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold: f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or COLORS['text']}; background-color:transparent;")
    return l


class _Sig(QObject):
    refresh_done   = Signal(int)
    status_update  = Signal(str, str)


class DealsView(QFrame):

    def __init__(self, parent=None, on_game_click=None, **kwargs):
        super().__init__(parent)
        self.on_game_click = on_game_click
        self._refreshing   = False
        self._sig          = _Sig()
        self._sig.refresh_done.connect(self._on_refresh_done)
        self._sig.status_update.connect(self._set_status)
        self.setStyleSheet(f"background:{COLORS['bg']};")
        self._countdown_timer = QTimer()
        self._countdown_timer.setInterval(1000)  # tick every second
        self._countdown_timer.timeout.connect(self._tick_countdown)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(52)
        header.setStyleSheet(f"background:{COLORS['panel']}; border:none;")
        hb = QHBoxLayout(header)
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
            QPushButton:disabled {{ color:{COLORS['text_dim']}; }}
        """)
        self._refresh_btn.clicked.connect(self._refresh_all_prices)
        hb.addWidget(self._refresh_btn)
        root.addWidget(header)

        # Scroll
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
            QScrollBar:vertical {{
                background:{COLORS['bg']}; width:6px; border:none;
            }}
            QScrollBar::handle:vertical {{
                background:{COLORS['border']}; border-radius:3px; min-height:30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        root.addWidget(scroll, 1)
        self.refresh()

    def hideEvent(self, event):
        self._countdown_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # Restart countdown when view becomes visible
        if hasattr(self, "_countdown_lbl"):
            self._countdown_timer.start()

    def _set_status(self, text: str, color: str):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(f"color:{color}; background:transparent;")

    def refresh(self):
        self._countdown_timer.stop()

        # Clear content
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        self._render_hero()
        self._render_sale_cards()
        self._render_on_sale()
        self._content_lay.addStretch()

        # Pre-generate banners in background
        threading.Thread(target=self._pregenerate_banners, daemon=True).start()

    def _pregenerate_banners(self):
        from services.sale_images import get_banner_path
        today  = date.today()
        events = [e for e in STEAM_SALE_EVENTS
                  if datetime.strptime(e["end"], "%Y-%m-%d").date() >= today]
        for event in events:
            try:
                get_banner_path(event["key"], event["color_top"],
                                event["color_bot"], event["emoji"])
            except Exception:
                pass
        QTimer.singleShot(100, self._apply_all_banners)

    def _apply_all_banners(self):
        from services.sale_images import get_banner_path
        today  = date.today()
        events = [e for e in STEAM_SALE_EVENTS
                  if datetime.strptime(e["end"], "%Y-%m-%d").date() >= today]
        for event in events:
            try:
                path = get_banner_path(event["key"], event["color_top"],
                                       event["color_bot"], event["emoji"])
                if hasattr(self, f"_banner_{event['key']}"):
                    banner_lbl = getattr(self, f"_banner_{event['key']}")
                    px = QPixmap(path)
                    if not px.isNull():
                        px = px.scaled(600, BAND_H,
                                       Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                       Qt.TransformationMode.SmoothTransformation)
                        banner_lbl.setPixmap(px)
            except Exception:
                pass

    # ── Hero countdown ────────────────────────────────────────────────────────

    def _render_hero(self):
        """Show a large countdown for the next/active Steam sale."""
        today   = date.today()
        now     = datetime.now()
        events  = sorted(
            [e for e in STEAM_SALE_EVENTS
             if datetime.strptime(e["end"], "%Y-%m-%d").date() >= today],
            key=lambda e: e["start"])

        if not events:
            return

        event     = events[0]
        start     = datetime.strptime(event["start"], "%Y-%m-%d")
        end       = datetime.strptime(event["end"],   "%Y-%m-%d")
        is_active = start.date() <= today <= end.date()
        target    = end if is_active else start
        name      = i18n.t(f"sale_events.{event['key']}")
        color     = event["color_top"]
        emoji     = event["emoji"]

        # Hero card
        hero = QFrame()
        hero.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {color}33, stop:1 {COLORS['card']}
                );
                border: 2px solid {color}88;
                border-radius: 16px;
                margin-bottom: 8px;
            }}
        """)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(28, 24, 28, 24)
        hl.setSpacing(8)

        # Status badge
        badge_text  = "🟢  ACTIVE NOW" if is_active else "⏳  COMING SOON"
        badge_color = COLORS["green"] if is_active else COLORS["gold"]
        badge = QLabel(badge_text)
        badge.setFont(QFont("Space Mono", 10, QFont.Weight.Bold))
        badge.setStyleSheet(f"color:{badge_color};")
        hl.addWidget(badge)

        # Event name
        title_row = QHBoxLayout()
        emoji_lbl = QLabel(emoji)
        emoji_lbl.setFont(QFont("", 36))
        title_row.addWidget(emoji_lbl)

        title = QLabel(name)
        title.setFont(QFont("Space Mono", 26, QFont.Weight.Bold))
        title.setStyleSheet(f"color:#fff;")
        title_row.addWidget(title, 1)
        hl.addLayout(title_row)

        # Countdown label
        self._hero_label_text = "ends in" if is_active else "starts in"
        self._hero_target     = target
        self._hero_event_name = name

        countdown_row = QHBoxLayout()
        lbl_prefix = QLabel("Ends in:" if is_active else "Starts in:")
        lbl_prefix.setFont(QFont("Space Mono", 13))
        lbl_prefix.setStyleSheet(f"color:{COLORS['text_dim']};")
        countdown_row.addWidget(lbl_prefix)

        self._countdown_lbl = QLabel()
        self._countdown_lbl.setFont(QFont("Space Mono", 32, QFont.Weight.Bold))
        self._countdown_lbl.setStyleSheet(f"color:{color};")
        countdown_row.addWidget(self._countdown_lbl)
        countdown_row.addStretch()
        hl.addLayout(countdown_row)

        # Dates
        dates_lbl = QLabel(f"{event['start']}  →  {event['end']}")
        dates_lbl.setFont(QFont("Space Mono", 11))
        dates_lbl.setStyleSheet(f"color:{COLORS['text_dim']};")
        hl.addWidget(dates_lbl)

        # Wishlist games on sale count
        games_on_sale = len([g for g in __import__("data.repository", fromlist=["get_on_sale"]).get_on_sale()])
        if games_on_sale > 0:
            sale_lbl = QLabel(f"⚡  {games_on_sale} game{'s' if games_on_sale != 1 else ''} from your wishlist on sale right now")
            sale_lbl.setFont(QFont("Space Mono", 11, QFont.Weight.Bold))
            sale_lbl.setStyleSheet(f"color:{COLORS['green']};")
            hl.addWidget(sale_lbl)

        self._content_lay.addWidget(hero)
        self._tick_countdown()
        self._countdown_timer.start()
        # Add image overlay label (behind content)
        self._hero_img_lbl = QLabel(hero)
        self._hero_img_lbl.setGeometry(0, 0, 760, 170)
        self._hero_img_lbl.setStyleSheet("background:transparent;")
        self._hero_img_lbl.lower()

        # Load sale art in background — placeholder or live depending on state
        threading.Thread(
            target=self._load_hero_image,
            args=(event, is_active, hero, self._hero_img_lbl),
            daemon=True
        ).start()

    # ── Sale image loading ────────────────────────────────────────────────────

    def _load_hero_image(self, event: dict, is_active: bool,
                         hero_frame: QFrame, hero_img_lbl: "QLabel"):
        """
        Smart sale image loading:
        - If event is UPCOMING: use placeholder_img (previous year's art)
        - If event is ACTIVE: probe Steam CDN for this year's actual live art
          using known URL patterns, fallback to placeholder_img
        """
        import urllib.request, ssl, certifi
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import QByteArray
        from datetime import datetime as _dt

        ctx = ssl.create_default_context(cafile=certifi.where())

        def _try_url(url: str) -> "QPixmap | None":
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0 SteamCurator"})
                with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                    data = resp.read()
                px = QPixmap()
                px.loadFromData(QByteArray(data))
                return px if not px.isNull() else None
            except Exception:
                return None

        urls_to_try = []

        if is_active:
            # Try to find this year's live art on Steam CDN
            year = _dt.now().year
            key  = event["key"]
            base_name = key.rsplit("_", 1)[0]  # e.g. "summer_sale"

            # Steam CDN patterns for live sales (most common)
            CDN = "https://cdn.cloudflare.steamstatic.com/steam/clusters"
            patterns = {
                "summer_sale":    f"{CDN}/grand_summer_sale_{year}/page_bg_english.jpg",
                "winter_sale":    f"{CDN}/winter_sale_{year}/page_bg_english.jpg",
                "autumn_sale":    f"{CDN}/sale_autumn{year}/assets/SteamAutumnSale{year}_PageBackground.jpg",
                "halloween_sale": f"{CDN}/sale_halloween{year}/assets/SteamHalloween{year}_PageBackground.jpg",
                "spring_sale":    f"{CDN}/sale_spring{year}/assets/SpringSale{year}_PageBackground.jpg",
                "black_friday":   f"{CDN}/sale_autumn{year}/assets/SteamAutumnSale{year}_PageBackground.jpg",
                "lunar_new_year": f"{CDN}/sale_lunarnewyear{year}/assets/LNY{year}_PageBackground.jpg",
            }
            if base_name in patterns:
                urls_to_try.append(patterns[base_name])

        # Always append the placeholder as final fallback
        placeholder = event.get("placeholder_img", "")
        if placeholder:
            urls_to_try.append(placeholder)

        # Try URLs in order
        px = None
        for url in urls_to_try:
            px = _try_url(url)
            if px:
                print(f"[Deals] Loaded sale image from: {url[:60]}...")
                break

        if px:
            QTimer.singleShot(0, lambda p=px, l=hero_img_lbl, f=hero_frame:
                              self._apply_hero_image(p, l, f))

    def _apply_hero_image(self, px: "QPixmap", img_lbl: "QLabel", frame: QFrame):
        """Apply image as background overlay behind hero content."""
        w = frame.width()  or 760
        h = frame.height() or 170
        scaled = px.scaled(w, h,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
        # Crop to exact size
        from PySide6.QtCore import QRect
        x_off = max(0, (scaled.width()  - w) // 2)
        y_off = max(0, (scaled.height() - h) // 2)
        cropped = scaled.copy(QRect(x_off, y_off, w, h))
        img_lbl.setPixmap(cropped)
        img_lbl.setGeometry(0, 0, w, h)
        img_lbl.lower()

    def _tick_countdown(self):
        """Update countdown every second."""
        if not hasattr(self, "_countdown_lbl") or not self._countdown_lbl:
            self._countdown_timer.stop()
            return
        try:
            delta  = self._hero_target - datetime.now()
            total  = int(delta.total_seconds())
            if total <= 0:
                self._countdown_lbl.setText("NOW!")
                self._countdown_timer.stop()
                return
            days   = total // 86400
            hours  = (total % 86400) // 3600
            mins   = (total % 3600)  // 60
            secs   = total % 60
            if days > 0:
                self._countdown_lbl.setText(f"{days}d  {hours:02d}h  {mins:02d}m  {secs:02d}s")
            else:
                self._countdown_lbl.setText(f"{hours:02d}h  {mins:02d}m  {secs:02d}s")
        except Exception:
            self._countdown_timer.stop()

    # ── Sale calendar ─────────────────────────────────────────────────────────

    def _render_sale_cards(self):
        self._content_lay.addWidget(
            _lbl(i18n.t("deals.upcoming"), 13, bold=True, color=COLORS["text_dim"]))

        today  = date.today()
        events = sorted(
            [e for e in STEAM_SALE_EVENTS
             if datetime.strptime(e["end"], "%Y-%m-%d").date() >= today],
            key=lambda e: e["start"])

        grid_w = QWidget()
        grid_w.setStyleSheet("background:transparent;")
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 8, 0, 16)
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        for idx, event in enumerate(events):
            card = self._make_sale_card(event, today)
            grid.addWidget(card, idx // 2, idx % 2)

        self._content_lay.addWidget(grid_w)

    def _make_sale_card(self, event: dict, today: date) -> QFrame:
        start = datetime.strptime(event["start"], "%Y-%m-%d").date()
        end   = datetime.strptime(event["end"],   "%Y-%m-%d").date()

        is_active     = start <= today <= end
        days_to_start = (start - today).days if start > today else 0
        days_left     = (end   - today).days if is_active else 0

        name      = i18n.t(f"sale_events.{event['key']}")
        top_color = event["color_top"]
        confirmed = event["confirmed"]

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background:{COLORS['card']};
                border:{'2' if is_active else '1'}px solid {top_color if is_active else COLORS['border']};
                border-radius:12px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # Banner
        banner = QFrame()
        banner.setFixedHeight(BAND_H)
        banner.setStyleSheet(f"background:{top_color}; border-radius:10px 10px 0 0;")
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(14, 0, 14, 0)

        # Store reference for later image apply
        banner_lbl = QLabel()
        banner_lbl.setStyleSheet("background:transparent;")
        banner_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        setattr(self, f"_banner_{event['key']}", banner_lbl)

        # Text overlay
        text_w = QWidget()
        text_w.setStyleSheet("background:transparent;")
        tl = QVBoxLayout(text_w)
        tl.setContentsMargins(0, 8, 0, 8)
        tl.setSpacing(2)

        title_row = QHBoxLayout()
        emoji_lbl = QLabel(event["emoji"])
        emoji_lbl.setFont(QFont("", 20))
        emoji_lbl.setStyleSheet("background:transparent;")
        title_row.addWidget(emoji_lbl)
        name_lbl = QLabel(name)
        name_lbl.setFont(QFont("Space Mono", 14, QFont.Weight.Bold))
        name_lbl.setStyleSheet("color:#fff; background:transparent;")
        title_row.addWidget(name_lbl)
        title_row.addStretch()
        tl.addLayout(title_row)

        badge_text  = (i18n.t("deals.active_now") if is_active
                       else i18n.t("deals.confirmed") if confirmed
                       else i18n.t("deals.estimated"))
        badge_col   = COLORS["green"] if is_active else COLORS["border"]
        badge = QLabel(badge_text)
        badge.setFont(QFont("Space Mono", 9))
        badge.setStyleSheet(f"""
            background:{badge_col}; color:#fff;
            border-radius:4px; padding:1px 6px;
        """)
        tl.addWidget(badge)
        bl.addWidget(text_w)
        cl.addWidget(banner)

        # Info strip
        info_w = QWidget()
        info_w.setStyleSheet("background:transparent;")
        il = QHBoxLayout(info_w)
        il.setContentsMargins(14, 8, 14, 10)
        il.addWidget(_lbl(f"{event['start']}  →  {event['end']}", 11,
                          color=COLORS["text_dim"]))
        il.addStretch()

        status_text  = (i18n.t("deals.days_left",  n=days_left)  if is_active
                        else i18n.t("deals.starts_in", n=days_to_start))
        status_color = COLORS["green"] if is_active else COLORS["text"]
        il.addWidget(_lbl(status_text, 12, bold=True, color=status_color))
        cl.addWidget(info_w)
        return card

    # ── On-sale games ─────────────────────────────────────────────────────────

    def _render_on_sale(self):
        games    = repo.get_on_sale()
        currency = next((g.price.currency for g in games if g.price), "")

        header_row = QWidget()
        header_row.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(header_row)
        hl.setContentsMargins(0, 4, 0, 6)
        hl.addWidget(_lbl(i18n.t("deals.on_sale"), 13, bold=True,
                          color=COLORS["text_dim"]))
        hl.addStretch()
        if currency:
            hl.addWidget(_lbl(i18n.t("deals.currency_note", currency=currency),
                              10, color=COLORS["text_dim"]))
        self._content_lay.addWidget(header_row)

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
            QFrame:hover {{ border-color:{COLORS['blue']}44; }}
        """)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.mousePressEvent = lambda e: self.on_game_click(game) if self.on_game_click else None

        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 10, 14, 10)

        badge = QLabel(game.priority)
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color = PRIORITY_COLORS.get(game.priority, "#666")
        badge.setStyleSheet(f"""
            background:{color}; color:{"#1a0f00" if game.priority=="S" else "#fff"};
            border-radius:4px; font-family:'Space Mono'; font-weight:bold; font-size:11px;
        """)
        rl.addWidget(badge)

        info = QWidget()
        info.setStyleSheet("background:transparent;")
        il = QVBoxLayout(info)
        il.setContentsMargins(8, 0, 0, 0)
        il.setSpacing(1)
        il.addWidget(_lbl(game.name, 13, bold=True))
        genre = game.genre.split(",")[0] if game.genre else "—"
        il.addWidget(_lbl(f"{genre} · {game.release_year or '—'}", 11,
                          color=COLORS["text_dim"]))
        rl.addWidget(info, 1)

        if game.price:
            prices = QWidget()
            prices.setStyleSheet("background:transparent;")
            pl = QHBoxLayout(prices)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(8)

            if game.price.discount_pct:
                disc = QLabel(f"-{game.price.discount_pct}%")
                disc.setFixedSize(50, 24)
                disc.setAlignment(Qt.AlignmentFlag.AlignCenter)
                disc.setFont(QFont("Space Mono", 11, QFont.Weight.Bold))
                disc.setStyleSheet(f"background:{COLORS['green']}; color:#fff; border-radius:4px;")
                pl.addWidget(disc)

            pl.addWidget(_lbl(f"${game.price.base:,.0f}", 11, color=COLORS["text_dim"]))
            pl.addWidget(_lbl(f"${game.price.current:,.0f} {game.price.currency}",
                              14, bold=True, color=COLORS["green"]))
            rl.addWidget(prices)

        return row

    # ── Refresh prices ────────────────────────────────────────────────────────

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

    def _on_refresh_done(self, total: int):
        self._refreshing = False
        self._refresh_btn.setEnabled(True)
        self._sig.status_update.emit(
            i18n.t("settings.refresh_done", n=total), COLORS["green"])
        QTimer.singleShot(4000, lambda: self._sig.status_update.emit("", COLORS["green"]))
        self.refresh()
