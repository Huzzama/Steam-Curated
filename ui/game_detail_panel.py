"""
GameDetailPanel — PySide6.
Side panel showing game details, price, recommendation, edit controls.
"""
import threading
import webbrowser
import subprocess
import sys
from typing import Optional, Callable

from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QTextEdit, QProgressBar,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QPixmap

from config import COLORS, PRIORITY_OPTIONS, PRIORITY_COLORS
from data.models import Game
import data.repository as repo
import services.steam_api as steam
import services.steamdb_scraper as steamdb
import services.steamgriddb as sgdb
from ui.settings_loader import get_settings
import i18n


def open_steam_page(app_id: str, fallback_url: str):
    steam_url = f"steam://store/{app_id}"
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", steam_url])
        elif sys.platform == "win32":
            subprocess.Popen(["start", steam_url], shell=True)
        else:
            subprocess.Popen(["xdg-open", steam_url])
    except Exception:
        webbrowser.open(fallback_url)


class _Sig(QObject):
    reload = Signal(object)   # Game


def _lbl(text, size=10, bold=False, color=None, wrap=0):
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold: f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or COLORS['text']}; background-color:transparent;")
    if wrap: l.setWordWrap(True)
    return l


def _divider():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{COLORS['border']}; margin:8px 12px;")
    return f


def _ghost_btn(text, command=None, danger=False):
    btn = QPushButton(text)
    btn.setFixedHeight(30)
    border = "#4a1515" if danger else COLORS["border"]
    fg     = COLORS["red"] if danger else COLORS["text_dim"]
    hover  = "#2a0a0a" if danger else COLORS["card_hover"]
    btn.setStyleSheet(f"""
        QPushButton {{
            background:transparent; color:{fg};
            border:1px solid {border}; border-radius:6px;
            font-family:'Space Mono'; font-size:10px;
            padding:0 8px;
        }}
        QPushButton:hover {{ background:{hover}; }}
    """)
    if command:
        btn.clicked.connect(command)
    return btn


class GameDetailPanel(QFrame):

    def __init__(self, parent=None,
                 on_close: Callable = None,
                 on_refresh: Callable = None, **kwargs):
        super().__init__(parent)
        self.on_close   = on_close   or (lambda: None)
        self.on_refresh = on_refresh or (lambda: None)
        self._game: Optional[Game] = None
        self._sig = _Sig()
        self._sig.reload.connect(self.load_game)

        self.setStyleSheet(f"""
            GameDetailPanel {{
                background:{COLORS['panel']};
                border-left:1px solid {COLORS['border']};
            }}
        """)
        self._build_shell()

    def _build_shell(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        topbar = QFrame()
        topbar.setFixedHeight(42)
        topbar.setStyleSheet(f"background:{COLORS['bg']}; border:none;")
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(12, 0, 6, 0)

        self._title_lbl = _lbl("", 12, bold=True)
        tb.addWidget(self._title_lbl)
        tb.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{COLORS['text_dim']};
                border:none; border-radius:6px; font-size:13px; }}
            QPushButton:hover {{ background:{COLORS['card_hover']}; }}
        """)
        close_btn.clicked.connect(self.on_close)
        tb.addWidget(close_btn)
        root.addWidget(topbar)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ border:none; background:{COLORS['panel']}; }}
            QScrollBar:vertical {{
                background:{COLORS['panel']}; width:4px; border:none;
            }}
            QScrollBar::handle:vertical {{
                background:{COLORS['border']}; border-radius:2px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        self._content = QWidget()
        self._content.setStyleSheet(f"background:{COLORS['panel']};")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(0, 0, 0, 16)
        self._content_lay.setSpacing(0)
        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll, 1)

    def load_game(self, game: Game):
        self._game = game
        self._title_lbl.setText(game.name)
        # Clear content
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._render(game)

    # ── Render ────────────────────────────────────────────────────────────────

    def _render(self, game: Game):
        lay = self._content_lay
        P   = 12

        def add(w, **pack_kw):
            lay.addWidget(w)

        # Cover
        cov_lbl = QLabel()
        cov_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cov_lbl.setStyleSheet("background:transparent;")
        if game.cover_path:
            px = QPixmap(game.cover_path)
            if not px.isNull():
                px = px.scaled(160, 240, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                cov_lbl.setPixmap(px)
        cov_lbl.setContentsMargins(0, 12, 0, 0)
        add(cov_lbl)

        # Priority badge
        badge_row = QWidget()
        badge_row.setStyleSheet("background:transparent;")
        br = QHBoxLayout(badge_row)
        br.setContentsMargins(P, 8, P, 0)
        br.setSpacing(6)
        badge = QLabel(game.priority)
        badge.setFixedSize(24, 24)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color = PRIORITY_COLORS.get(game.priority, "#666")
        badge.setStyleSheet(f"""
            background:{color}; color:#000; border-radius:4px;
            font-family:'Space Mono'; font-weight:bold; font-size:10px;
        """)
        br.addWidget(badge)
        br.addWidget(_lbl(i18n.t(f"priority.{game.priority}"), 10,
                          color=COLORS["text_dim"]))
        br.addStretch()
        add(badge_row)

        # Game name
        name_lbl = _lbl(game.name, 13, bold=True)
        name_lbl.setWordWrap(True)
        name_lbl.setContentsMargins(P, 4, P, 0)
        add(name_lbl)

        # Steam button
        if game.app_id:
            steam_btn = QPushButton(i18n.t("detail.check_on_steam"))
            steam_btn.setFixedHeight(32)
            steam_btn.setStyleSheet(f"""
                QPushButton {{ background:#1B2838; color:{COLORS['blue']};
                    border:1px solid {COLORS['blue']}; border-radius:6px;
                    font-family:'Space Mono'; font-size:12px; font-weight:bold;
                    margin:8px {P}px 0 {P}px; }}
                QPushButton:hover {{ background:#2a475e; }}
            """)
            steam_btn.clicked.connect(
                lambda: open_steam_page(game.app_id, game.steam_url))
            add(steam_btn)

        # Purchased / Buy button
        import data.purchase_repository as purchases
        bought = purchases.get_by_app_id(game.app_id)
        if bought:
            b_frame = QFrame()
            b_frame.setStyleSheet(f"""
                QFrame {{ background:#0a1f0a; border:1px solid #1a4a1a;
                          border-radius:8px; margin:{4}px {P}px 0 {P}px; }}
            """)
            bf = QHBoxLayout(b_frame)
            bf.setContentsMargins(12, 8, 12, 8)
            bf.addWidget(_lbl(f"✓  Purchased {bought.edition} Edition",
                              11, bold=True, color=COLORS["green"]))
            bf.addStretch()
            bf.addWidget(_lbl(
                f"${bought.price_paid:,.2f} {bought.currency}  ·  {bought.purchased_at}",
                10, color=COLORS["text_dim"]))
            add(b_frame)
        else:
            buy_btn = QPushButton("🛒  I bought this game")
            buy_btn.setFixedHeight(34)
            buy_btn.setStyleSheet(f"""
                QPushButton {{ background:{COLORS['green']}; color:#000;
                    border:none; border-radius:6px;
                    font-family:'Space Mono'; font-size:12px; font-weight:bold;
                    margin:8px {P}px 0 {P}px; }}
                QPushButton:hover {{ background:#86efac; }}
            """)
            buy_btn.clicked.connect(lambda: self._mark_purchased(game))
            add(buy_btn)

        add(_divider())
        self._render_price(lay, game, P)
        add(_divider())
        self._render_price_compare(lay, game, P)
        add(_divider())
        self._render_recommendation(lay, game, P)
        add(_divider())

        # Metadata
        for label, value in [
            (i18n.t("game.genre"),    game.genre or "—"),
            (i18n.t("game.year"),     str(game.release_year) if game.release_year else "—"),
            (i18n.t("game.developer"),game.developer or "—"),
            (i18n.t("game.publisher"),game.publisher or "—"),
        ]:
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(P, 1, P, 1)
            l1 = _lbl(label + ":", 10, color=COLORS["text_dim"])
            l1.setFixedWidth(90)
            l2 = _lbl(value, 10)
            l2.setWordWrap(True)
            rl.addWidget(l1)
            rl.addWidget(l2, 1)
            add(row)

        add(_divider())
        self._render_edit(lay, game, P)

        # Action buttons
        for text, cmd, danger in [
            (i18n.t("detail.refresh_prices"), lambda: self._refresh_prices(game), False),
            (i18n.t("detail.retry_cover"),    lambda: self._download_cover(game), False),
            (i18n.t("detail.delete_game"),    lambda: self._delete(game),         True),
        ]:
            btn = _ghost_btn(text, cmd, danger)
            btn.setContentsMargins(P, 0, P, 0)
            w = QWidget()
            w.setStyleSheet("background:transparent;")
            wl = QVBoxLayout(w)
            wl.setContentsMargins(P, 2, P, 2)
            wl.addWidget(btn)
            add(w)

        lay.addStretch()

    # ── Price section ─────────────────────────────────────────────────────────

    def _render_price(self, lay, game: Game, P: int):
        frame = QWidget()
        frame.setStyleSheet("background:transparent;")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(P, 0, P, 0)
        fl.setSpacing(2)

        if game.price:
            p = game.price
            pr = QHBoxLayout()
            price_lbl = _lbl(f"${p.current:,.0f} {p.currency}", 20, bold=True,
                             color=COLORS["green"] if p.is_on_sale else COLORS["text"])
            pr.addWidget(price_lbl)
            if p.discount_pct:
                disc = QLabel(f"-{p.discount_pct}%")
                disc.setFixedHeight(22)
                disc.setAlignment(Qt.AlignmentFlag.AlignCenter)
                disc.setFont(QFont("Space Mono", 10, QFont.Weight.Bold))
                disc.setStyleSheet(f"""
                    background:{COLORS['green']}; color:#fff;
                    border-radius:4px; padding:0 6px;
                """)
                pr.addWidget(disc)
            pr.addStretch()
            fl.addLayout(pr)
            if p.base != p.current:
                fl.addWidget(_lbl(
                    f"{i18n.t('detail.base_price')}: ${p.base:,.0f}",
                    10, color=COLORS["text_dim"]))

        if game.price_history and game.price_history.all_time_low > 0:
            h = game.price_history
            fl.addWidget(_lbl(
                f"{i18n.t('game.price_low')}: ${h.all_time_low:,.0f}",
                11, bold=True, color=COLORS["blue"]))
            if h.all_time_low_date:
                fl.addWidget(_lbl(h.all_time_low_date, 9,
                                  color=COLORS["text_dim"]))

            if game.price_diff_pct is not None:
                diff = game.price_diff_pct
                rec  = game.buy_recommendation
                col  = (COLORS["green"] if diff <= 5 else
                        COLORS["gold"]  if diff <= 25 else COLORS["red"])
                fl.addWidget(_lbl(f"→ {rec}", 11, bold=True, color=col))

                prog = QProgressBar()
                prog.setFixedHeight(6)
                prog.setRange(0, 100)
                prog.setValue(max(0, min(100, int((1 - diff/100)*100))))
                prog.setTextVisible(False)
                bar_col = COLORS["green"] if diff <= 5 else COLORS["gold"]
                prog.setStyleSheet(f"""
                    QProgressBar {{ background:{COLORS['border']}; border-radius:3px; }}
                    QProgressBar::chunk {{ background:{bar_col}; border-radius:3px; }}
                """)
                fl.addWidget(prog)

        lay.addWidget(frame)

    # ── Price comparator ─────────────────────────────────────────────────────

    def _render_price_compare(self, lay, game: Game, P: int):
        """Show price in configured regions vs user's base currency."""
        from ui.settings_loader import get_settings
        settings = get_settings()

        # Get user's base region and compare regions
        base_cc      = settings.get("country", "mx")
        compare_ccs  = settings.get("compare_regions",
                                    ["us", "ar", "br"])
        # Always show base first, then compare regions (no duplicates)
        all_regions  = [base_cc] + [r for r in compare_ccs if r != base_cc]

        # Region display names from i18n
        def region_name(cc): return i18n.t(f"regions.{cc}")

        frame = QWidget()
        frame.setStyleSheet("background:transparent;")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(P, 0, P, 0)
        fl.setSpacing(4)
        fl.addWidget(_lbl(i18n.t("detail.price_by_region"), 11, bold=True))

        self._compare_labels: dict[str, tuple] = {}  # cc -> (price_lbl, diff_lbl)
        for cc in all_regions:
            row = QWidget(); row.setStyleSheet("background:transparent;")
            rl  = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(8)

            # Flag + region name
            name_lbl = _lbl(region_name(cc), 10, color=COLORS["text_dim"])
            name_lbl.setFixedWidth(120)
            rl.addWidget(name_lbl)

            # Price (loading…)
            price_lbl = _lbl("…", 11, bold=True)
            rl.addWidget(price_lbl)

            # % diff vs base (only for non-base regions)
            diff_lbl = _lbl("", 10)
            if cc == base_cc:
                diff_lbl.setText("← base")
                diff_lbl.setStyleSheet(f"color:{COLORS['blue']}; background:transparent;")
            rl.addWidget(diff_lbl)
            rl.addStretch()

            self._compare_labels[cc] = (price_lbl, diff_lbl)
            fl.addWidget(row)

        lay.addWidget(frame)

        # Fetch all regions in background
        import threading as _t
        import services.steam_api as _steam

        def _fetch():
            prices: dict = {}
            for cc in all_regions:
                try:
                    p = _steam.refresh_price(game.app_id, country=cc)
                    prices[cc] = p
                except Exception:
                    prices[cc] = None

            # Update labels on main thread
            base_price = prices.get(base_cc)
            base_val   = base_price.current if base_price else None

            for cc in all_regions:
                p = prices.get(cc)
                pl, dl = self._compare_labels.get(cc, (None, None))
                if not pl: continue

                if p:
                    txt = f"{p.current:,.0f} {p.currency}"
                    if p.is_on_sale:
                        txt += f"  -{p.discount_pct}%"
                    col = COLORS["green"] if p.is_on_sale else COLORS["text"]
                else:
                    txt = "N/A"; col = COLORS["text_dim"]

                # Calculate % diff vs base for non-base regions
                diff_txt = "← base" if cc == base_cc else ""
                diff_col = COLORS["blue"]
                if cc != base_cc and base_val and p and p.current:
                    # We can't compare directly (different currencies)
                    # Show relative to base price % discount from MSRP instead
                    base_disc = base_price.discount_pct if base_price else 0
                    this_disc = p.discount_pct
                    diff = this_disc - base_disc
                    if diff > 0:
                        diff_txt = f"+{diff}% cheaper"
                        diff_col = COLORS["green"]
                    elif diff < 0:
                        diff_txt = f"{diff}% pricier"
                        diff_col = COLORS["red"]
                    else:
                        diff_txt = "same deal"
                        diff_col = COLORS["text_dim"]

                QTimer.singleShot(0, lambda l=pl, t=txt, c=col: (
                    l.setText(t), l.setStyleSheet(f"color:{c}; background:transparent;")))
                if dl:
                    QTimer.singleShot(0, lambda l=dl, t=diff_txt, c=diff_col: (
                        l.setText(t), l.setStyleSheet(f"color:{c}; background:transparent;")))

        _t.Thread(target=_fetch, daemon=True).start()

    # ── Recommendation ────────────────────────────────────────────────────────

    def _render_recommendation(self, lay, game: Game, P: int):
        try:
            from services.recommendation import get_recommendation
            rec = get_recommendation(game)
        except Exception:
            return

        colors   = {"buy_now": COLORS["green"], "good_deal": COLORS["blue"],
                    "wait": COLORS["gold"], "no_data": COLORS["text_dim"]}
        icons    = {"buy_now": "✓", "good_deal": "◎", "wait": "⏳", "no_data": "—"}
        accent   = colors.get(rec["verdict"], COLORS["text_dim"])
        icon     = icons.get(rec["verdict"], "—")

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background:{COLORS['card']};
                border:1px solid {COLORS['border']};
                border-left:3px solid {accent};
                border-radius:8px;
                margin:0 {P}px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 10, 10, 10)
        cl.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(_lbl(icon, 15, bold=True, color=accent))
        header.addWidget(_lbl(rec["headline"], 11, bold=True, color=accent))
        header.addStretch()
        cl.addLayout(header)

        if rec.get("reason"):
            rl = _lbl(rec["reason"], 10, color=COLORS["text_dim"], wrap=1)
            cl.addWidget(rl)

        if rec.get("next_sale"):
            sale_box = QFrame()
            sale_box.setStyleSheet(f"""
                QFrame {{ background:{COLORS['bg']};
                    border:1px solid {COLORS['border']}; border-radius:6px; }}
            """)
            sb = QVBoxLayout(sale_box)
            sb.setContentsMargins(10, 6, 10, 8)
            sb.addWidget(_lbl("NEXT LIKELY SALE", 9, color=COLORS["text_dim"]))
            sb.addWidget(_lbl(rec["next_sale"], 11, bold=True))
            cl.addWidget(sale_box)

        lay.addWidget(card)

    # ── Edit section ──────────────────────────────────────────────────────────

    def _render_edit(self, lay, game: Game, P: int):
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        wl = QVBoxLayout(w)
        wl.setContentsMargins(P, 0, P, 0)
        wl.setSpacing(4)

        wl.addWidget(_lbl(i18n.t("detail.edit_section"), 11, bold=True))
        wl.addWidget(_lbl(i18n.t("game.priority"), 10, color=COLORS["text_dim"]))

        p_row = QHBoxLayout()
        p_row.setSpacing(4)
        for p in PRIORITY_OPTIONS:
            color = PRIORITY_COLORS.get(p, "#666")
            btn = QPushButton(p)
            btn.setFixedSize(36, 28)
            active = game.priority == p
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:{"transparent" if not active else color};
                    color:#fff; border:1px solid {color};
                    border-radius:5px;
                    font-family:'Space Mono'; font-size:10px; font-weight:bold;
                }}
                QPushButton:hover {{ background:{color}; }}
            """)
            btn.clicked.connect(lambda _, pv=p: self._update_priority(game, pv))
            p_row.addWidget(btn)
            self.__dict__[f"_det_pb_{p}"] = btn
        p_row.addStretch()
        wl.addLayout(p_row)

        wl.addWidget(_lbl(i18n.t("game.notes"), 10, color=COLORS["text_dim"]))
        self._notes_box = QTextEdit()
        self._notes_box.setFixedHeight(60)
        self._notes_box.setStyleSheet(f"""
            QTextEdit {{
                background:{COLORS['card']}; color:{COLORS['text']};
                border:1px solid {COLORS['border']}; border-radius:4px;
                font-family:'Space Mono'; font-size:10px; padding:4px;
            }}
        """)
        if game.notes:
            self._notes_box.setPlainText(game.notes)
        wl.addWidget(self._notes_box)

        save_btn = QPushButton(i18n.t("actions.save"))
        save_btn.setFixedHeight(30)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background:{COLORS['blue']}; color:#0a1929;
                border:none; border-radius:6px;
                font-family:'Space Mono'; font-size:11px; font-weight:bold;
            }}
            QPushButton:hover {{ background:#4fa8d8; }}
        """)
        save_btn.clicked.connect(lambda: self._save_edits(game))
        wl.addWidget(save_btn)
        lay.addWidget(w)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _update_priority(self, game: Game, p: str):
        game.priority = p
        repo.update(game)
        for pr in PRIORITY_OPTIONS:
            color = PRIORITY_COLORS.get(pr, "#666")
            btn   = self.__dict__.get(f"_det_pb_{pr}")
            if btn:
                active = pr == p
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background:{"transparent" if not active else color};
                        color:#fff; border:1px solid {color};
                        border-radius:5px;
                        font-family:'Space Mono'; font-size:10px; font-weight:bold;
                    }}
                    QPushButton:hover {{ background:{color}; }}
                """)
        self.on_refresh()

    def _save_edits(self, game: Game):
        game.notes = self._notes_box.toPlainText().strip()
        repo.update(game)
        self.on_refresh()

    def _refresh_prices(self, game: Game):
        def _work():
            settings = get_settings()
            data = steam.get_app_details(
                game.app_id, country=settings.get("country", "mx"))
            if data:
                game.price = steam.parse_price(data)
            history = steamdb.get_price_history(game.app_id)
            if history:
                game.price_history = history
            repo.update(game)
            self._sig.reload.emit(game)
            QTimer.singleShot(0, self.on_refresh)
        threading.Thread(target=_work, daemon=True).start()

    def _download_cover(self, game: Game):
        def _work():
            settings = get_settings()
            api_key  = settings.get("steamgriddb_key", "")
            cover = sgdb.download_cover(game.app_id, api_key, game.name)
            if cover:
                game.cover_path = cover
                repo.update(game)
                self._sig.reload.emit(game)
                QTimer.singleShot(0, self.on_refresh)
        threading.Thread(target=_work, daemon=True).start()

    def _mark_purchased(self, game: Game):
        from ui.mark_purchased_dialog import MarkPurchasedDialog
        def _on_success(purchase):
            self.on_refresh()
            self._sig.reload.emit(game)
        dlg = MarkPurchasedDialog(self, game=game, on_success=_on_success)
        dlg.exec()

    def _delete(self, game: Game):
        repo.delete(game.id)
        self.on_close()
