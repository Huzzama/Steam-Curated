import json
import threading
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QCheckBox, QGridLayout,
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QScrollArea, QComboBox,
    QTextEdit,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont

from config import COLORS, LOCALES, PRIORITY_COLORS
import data.repository as repo
import i18n
from ui.library_view import translate_genre


# ── settings helpers ──────────────────────────────────────────────────────────

_DEFAULTS = {
    "locale":            "es",
    "steamgriddb_key":   "",
    "country":           "mx",
    "timezone":          "GMT-6",
    "steam_id64":        "",
    "steamkustom_token": "",
}

GMT_OPTIONS = [
    "GMT-12", "GMT-11", "GMT-10", "GMT-9", "GMT-8",
    "GMT-7",  "GMT-6",  "GMT-5",  "GMT-4", "GMT-3",
    "GMT-2",  "GMT-1",  "GMT+0",  "GMT+1", "GMT+2",
    "GMT+3",  "GMT+4",  "GMT+5",  "GMT+5:30",
    "GMT+6",  "GMT+7",  "GMT+8",  "GMT+9",
    "GMT+10", "GMT+11", "GMT+12",
]


def _settings_path():
    from config import BASE_DIR
    return BASE_DIR / "settings.json"


def load_settings() -> dict:
    p = _settings_path()
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                return {**_DEFAULTS, **json.load(f)}
        except Exception:
            pass
    return dict(_DEFAULTS)


def save_settings(data: dict) -> None:
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


MAX_HISTORY_ROWS = 60


# ── shared helpers ────────────────────────────────────────────────────────────

def _lbl(text, size=11, bold=False, color=None, wrap=False):
    l = QLabel(text)
    f = QFont("Space Mono", size)
    if bold: f.setBold(True)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or COLORS['text']}; background-color:transparent;")
    if wrap: l.setWordWrap(True)
    return l


def _entry(text="", placeholder="", password=False, width=300):
    e = QLineEdit(text)
    e.setPlaceholderText(placeholder)
    if password: e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setFixedHeight(36)
    e.setFixedWidth(width)
    e.setStyleSheet(f"""
        QLineEdit {{
            background:{COLORS['card']}; color:{COLORS['text']};
            border:1px solid {COLORS['border']}; border-radius:6px;
            padding:0 10px; font-family:'Space Mono'; font-size:11px;
        }}
        QLineEdit:focus {{ border-color:{COLORS['blue']}; }}
    """)
    return e


def _divider():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{COLORS['border']}; margin:0;")
    f.setFixedHeight(1)
    return f


def _section_header(text):
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    l = QVBoxLayout(w)
    l.setContentsMargins(0, 24, 0, 12)
    l.setSpacing(4)
    lbl = _lbl(text, 14, bold=True)
    l.addWidget(lbl)
    l.addWidget(_divider())
    return w


def _ghost_btn(text, command=None, color=None, width=None):
    btn = QPushButton(text)
    btn.setFixedHeight(32)
    if width: btn.setFixedWidth(width)
    c = color or COLORS["blue"]
    btn.setStyleSheet(f"""
        QPushButton {{
            background:transparent; color:{c};
            border:1px solid {c}; border-radius:6px;
            font-family:'Space Mono'; font-size:11px;
            padding:0 12px;
        }}
        QPushButton:hover {{ background:{COLORS['card']}; }}
        QPushButton:disabled {{ color:{COLORS['text_dim']}; border-color:{COLORS['border']}; }}
    """)
    if command: btn.clicked.connect(command)
    return btn


def _scroll_area(content_widget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content_widget)
    scroll.setStyleSheet(f"""
        QScrollArea {{ border:none; background:{COLORS['bg']}; }}
        QScrollBar:vertical {{
            background:{COLORS['bg']}; width:6px; border:none;
        }}
        QScrollBar::handle:vertical {{
            background:{COLORS['border']}; border-radius:3px; min-height:30px;
        }}
        QScrollBar::handle:vertical:hover {{ background:{COLORS['blue']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    """)
    return scroll


# ── HistoryView ───────────────────────────────────────────────────────────────

class HistoryView(QFrame):

    def __init__(self, parent=None, on_game_click: Callable = None, **kwargs):
        super().__init__(parent)
        self.on_game_click = on_game_click
        self._last_ids: list = []
        self.setObjectName("HistoryView")
        self.setStyleSheet(f"QFrame#HistoryView {{ background:{COLORS['bg']}; }}")
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(52)
        header.setObjectName("HistoryHeader")
        header.setStyleSheet(f"QFrame#HistoryHeader {{ background:{COLORS['panel']}; }}")
        hb = QHBoxLayout(header)
        hb.setContentsMargins(18, 0, 18, 0)
        hb.addWidget(_lbl(i18n.t("history.title"), 16, bold=True))
        hb.addStretch()
        root.addWidget(header)

        # ── Tab bar ───────────────────────────────────────────────────────────
        tab_bar = QWidget()
        tab_bar.setObjectName("HistoryTabBar")
        tab_bar.setStyleSheet(f"QWidget#HistoryTabBar {{ background:{COLORS['panel']}; border-bottom:1px solid {COLORS['border']}; }}")
        tab_bar.setFixedHeight(38)
        tbl = QHBoxLayout(tab_bar)
        tbl.setContentsMargins(18, 0, 18, 0)
        tbl.setSpacing(0)

        self._tab = "recently_added"

        def _tab_style(active):
            if active:
                return f"""
                    QPushButton {{
                        background:transparent; color:{COLORS['blue']};
                        border:none; border-bottom:2px solid {COLORS['blue']};
                        font-family:'Space Mono'; font-size:11px; font-weight:bold;
                        padding:0 16px;
                    }}
                """
            return f"""
                QPushButton {{
                    background:transparent; color:{COLORS['text_dim']};
                    border:none; border-bottom:2px solid transparent;
                    font-family:'Space Mono'; font-size:11px;
                    padding:0 16px;
                }}
                QPushButton:hover {{ color:{COLORS['text']}; }}
            """

        self._btn_recent   = QPushButton(i18n.t("history.recently_added"))
        self._btn_purchase = QPushButton(i18n.t("history.purchase_history"))
        self._btn_recent.setFixedHeight(38)
        self._btn_purchase.setFixedHeight(38)
        self._btn_recent.setStyleSheet(_tab_style(True))
        self._btn_purchase.setStyleSheet(_tab_style(False))

        def _switch(tab):
            self._tab = tab
            self._btn_recent.setStyleSheet(_tab_style(tab == "recently_added"))
            self._btn_purchase.setStyleSheet(_tab_style(tab == "purchases"))
            if tab == "recently_added":
                self._stack.setCurrentIndex(0)
                self.refresh()
            else:
                self._stack.setCurrentIndex(1)
                self._render_purchases()

        from PySide6.QtWidgets import QStackedWidget

        self._btn_recent.clicked.connect(lambda: _switch("recently_added"))
        self._btn_purchase.clicked.connect(lambda: _switch("purchases"))
        tbl.addWidget(self._btn_recent)
        tbl.addWidget(self._btn_purchase)
        tbl.addStretch()
        root.addWidget(tab_bar)

        # ── Stacked area — fills remaining space ──────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:transparent;")
        root.addWidget(self._stack, 1)

        # ── Page 0: Recently added ────────────────────────────────────────────
        self._content = QWidget()
        self._content.setObjectName("HistoryContent")
        self._content.setStyleSheet(f"QWidget#HistoryContent {{ background:{COLORS['bg']}; }}")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(16, 10, 16, 10)
        self._content_lay.setSpacing(0)

        self._empty_lbl = _lbl(i18n.t("history.empty"), 13,
                                color=COLORS["text_dim"])
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.hide()
        self._content_lay.addWidget(self._empty_lbl)
        self._content_lay.addStretch()

        self._scroll_area = _scroll_area(self._content)
        self._stack.addWidget(self._scroll_area)   # index 0

        # ── Page 1: Purchase history ──────────────────────────────────────────
        self._purchase_content = QWidget()
        self._purchase_content.setObjectName("PurchaseContent")
        self._purchase_content.setStyleSheet(f"QWidget#PurchaseContent {{ background:{COLORS['bg']}; }}")
        self._purchase_lay = QVBoxLayout(self._purchase_content)
        self._purchase_lay.setContentsMargins(16, 10, 16, 10)
        self._purchase_lay.setSpacing(6)
        purchase_scroll = _scroll_area(self._purchase_content)
        self._stack.addWidget(purchase_scroll)     # index 1

        # Pre-build pool
        self._month_labels: list[QLabel] = [
            _lbl("", 12, bold=True, color=COLORS["blue"]) for _ in range(12)
        ]
        self._row_pool: list[tuple] = []
        for _ in range(MAX_HISTORY_ROWS):
            row = QFrame()
            _rname = f"HistRow{_}"
            row.setObjectName(_rname)
            row.setStyleSheet(f"""
                QFrame#{_rname} {{
                    background:{COLORS['card']};
                    border:1px solid {COLORS['border']};
                    border-radius:8px;
                }}
                QFrame#{_rname}:hover {{ border-color:{COLORS['blue']}44; }}
            """)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12, 10, 14, 10)

            badge = QLabel("")
            badge.setFixedSize(22, 22)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFont(QFont("Space Mono", 10, QFont.Weight.Bold))
            badge.setStyleSheet(f"background:{COLORS['border']}; color:#fff; border-radius:4px;")
            rl.addWidget(badge)

            info = QWidget()
            info.setAutoFillBackground(False)
            il = QVBoxLayout(info)
            il.setContentsMargins(8, 0, 0, 0)
            il.setSpacing(1)
            name_lbl = _lbl("", 13, bold=True)
            meta_lbl = _lbl("", 11, color=COLORS["text_dim"])
            il.addWidget(name_lbl)
            il.addWidget(meta_lbl)
            rl.addWidget(info, 1)

            date_lbl = _lbl("", 11, color=COLORS["text_dim"])
            rl.addWidget(date_lbl)

            row.hide()
            self._row_pool.append((row, badge, name_lbl, meta_lbl, date_lbl))

        self.refresh()

    def refresh(self):
        games   = repo.get_recent(limit=50)
        new_ids = [g.id for g in games]
        if new_ids == self._last_ids:
            return
        self._last_ids = new_ids
        self._layout(games)

    def _render_purchases(self):
        """Render purchase history tab."""
        import data.purchase_repository as purchases
        from collections import defaultdict

        # Clear
        while self._purchase_lay.count():
            item = self._purchase_lay.takeAt(0)
            w = item.widget()
            if w:
                w.hide(); w.setParent(None)

        all_p = purchases.get_all()
        if not all_p:
            empty = _lbl(i18n.t("history.no_purchases"),
                         12, color=COLORS["text_dim"], wrap=True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._purchase_lay.addWidget(empty)
            self._purchase_lay.addStretch()
            return

        # Group by month
        by_month: dict = defaultdict(list)
        for p in sorted(all_p, key=lambda x: x.purchased_at, reverse=True):
            key = p.purchased_at[:7] if p.purchased_at else "—"
            by_month[key].append(p)

        BLUE  = COLORS["blue"]
        GREEN = COLORS["green"]
        GOLD  = COLORS.get("gold", "#fbbf24")
        DIM   = COLORS["text_dim"]
        CARD  = COLORS["card"]
        BORDER = COLORS["border"]

        for month_key in sorted(by_month.keys(), reverse=True):
            try:
                from datetime import datetime
                month_lbl_text = datetime.strptime(month_key, "%Y-%m").strftime("%B %Y").upper()
            except Exception:
                month_lbl_text = month_key
            self._purchase_lay.addWidget(
                _lbl(month_lbl_text, 12, bold=True, color=BLUE))
            self._purchase_lay.addSpacing(4)

            for i, p in enumerate(by_month[month_key]):
                rname = f"PurchRow{month_key}{i}"
                row = QFrame()
                row.setObjectName(rname)
                row.setStyleSheet(f"""
                    QFrame#{rname} {{
                        background:{CARD};
                        border:1px solid {BORDER};
                        border-radius:8px;
                    }}
                """)
                rl = QHBoxLayout(row)
                rl.setContentsMargins(14, 10, 14, 10)
                rl.setSpacing(10)

                # Left: name + edition
                info = QWidget(); info.setAutoFillBackground(False)
                il = QVBoxLayout(info); il.setContentsMargins(0,0,0,0); il.setSpacing(2)
                il.addWidget(_lbl(p.name, 12, bold=True))
                if p.edition and p.edition != i18n.t("history.standard_edition"):
                    il.addWidget(_lbl(p.edition, 10, color=GOLD))
                rl.addWidget(info, 1)

                # Right: price + saved + date
                price_col = QWidget(); price_col.setAutoFillBackground(False)
                pl = QVBoxLayout(price_col); pl.setContentsMargins(0,0,0,0); pl.setSpacing(2)
                pl.setAlignment(Qt.AlignmentFlag.AlignRight)
                price_lbl = _lbl(f"${p.price_paid:,.0f} {p.currency}", 12, bold=True, color=BLUE)
                price_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                pl.addWidget(price_lbl)
                if p.saved > 0:
                    saved_lbl = _lbl(f"saved ${p.saved:,.0f} (-{p.discount_pct}%)", 10, color=GREEN)
                    saved_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                    pl.addWidget(saved_lbl)
                rl.addWidget(price_col)

                date_lbl = _lbl(p.purchased_at or "", 10, color=DIM)
                date_lbl.setFixedWidth(85)
                date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                rl.addWidget(date_lbl)

                self._purchase_lay.addWidget(row)
            self._purchase_lay.addSpacing(12)

        self._purchase_lay.addStretch()

    def _layout(self, games):
        from collections import defaultdict
        lay = self._content_lay

        # Hide everything
        self._empty_lbl.hide()
        for lbl in self._month_labels:
            lbl.setParent(None)
        for row, *_ in self._row_pool:
            row.setParent(None)
            row.hide()

        # Remove stretch
        if lay.count() > 1:
            lay.takeAt(lay.count() - 1)

        if not games:
            self._empty_lbl.show()
            lay.addWidget(self._empty_lbl)
            lay.addStretch()
            return

        by_month: dict[str, list] = defaultdict(list)
        for g in games:
            key = g.date_added[:7] if g.date_added else "—"
            by_month[key].append(g)

        month_idx = row_idx = 0

        for month_key in sorted(by_month.keys(), reverse=True):
            if month_idx >= len(self._month_labels):
                break

            try:
                year, month = month_key.split("-")
                label = f"{i18n.t(f'months.{int(month)}')} {year}"
            except Exception:
                label = month_key

            m_lbl = self._month_labels[month_idx]
            m_lbl.setText(label)
            m_lbl.setContentsMargins(0, 14, 0, 4)
            lay.addWidget(m_lbl)
            m_lbl.show()
            month_idx += 1

            for game in by_month[month_key]:
                if row_idx >= len(self._row_pool):
                    break
                row, badge, name_lbl, meta_lbl, date_lbl = self._row_pool[row_idx]

                color = PRIORITY_COLORS.get(game.priority, COLORS["border"])
                badge.setStyleSheet(
                    f"background:{color}; color:"
                    f"{'#1a0f00' if game.priority=='S' else '#fff'};"
                    f" border-radius:4px;")
                badge.setText(game.priority)
                name_lbl.setText(game.name)
                genre = translate_genre(game.genre.split(",")[0].strip()) if game.genre else "—"
                meta_lbl.setText(f"{genre} · {game.developer or '—'}")
                date_lbl.setText(i18n.t("history.added_on", date=game.date_added))

                def _make_handler(g):
                    return lambda e: self.on_game_click(g) if self.on_game_click else None
                row.mousePressEvent = _make_handler(game)

                lay.addWidget(row)
                row.show()
                row_idx += 1

        lay.addStretch()


# ── SettingsView ──────────────────────────────────────────────────────────────

class _SettingsSig(QObject):
    update_status = Signal(str, str)   # text, color
    update_service = Signal(str, str, str)  # which, text, color
    verify_done = Signal(bool, object)


class SettingsView(QFrame):

    def __init__(self, parent=None, on_locale_change: Callable = None, **kwargs):
        super().__init__(parent)
        self.on_locale_change = on_locale_change or (lambda: None)
        self._settings    = load_settings()
        self._key_visible = False
        self._sig         = _SettingsSig()
        self._sig.verify_done.connect(self._on_verify_done)
        self.setStyleSheet(f"background:{COLORS['bg']};")
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
        hb.addWidget(_lbl(i18n.t("settings.title"), 16, bold=True))
        hb.addStretch()
        root.addWidget(header)

        # Scrollable content
        content_widget = QWidget()
        content_widget.setStyleSheet(f"background:{COLORS['bg']};")
        self._cl = QVBoxLayout(content_widget)
        self._cl.setContentsMargins(40, 10, 40, 30)
        self._cl.setSpacing(4)
        root.addWidget(_scroll_area(content_widget), 1)

        self._build_language()
        self._build_api_key()
        self._build_country()
        self._build_token()
        self._build_services()
        self._build_save()

    # ── Sections ──────────────────────────────────────────────────────────────

    def _build_language(self):
        self._cl.addWidget(_section_header(i18n.t("settings.language")))
        self._cl.addWidget(_lbl(i18n.t("settings.language_desc"), 11,
                                color=COLORS["text_dim"]))

        self._locale_combo = QComboBox()
        self._locale_combo.setFixedHeight(36)
        self._locale_combo.setFixedWidth(280)
        self._locale_combo.setStyleSheet(self._combo_style())
        locale_options = [f"{k} — {v}" for k, v in LOCALES.items()]
        self._locale_combo.addItems(locale_options)
        current = self._settings.get("locale", "es")
        for i, opt in enumerate(locale_options):
            if opt.startswith(current):
                self._locale_combo.setCurrentIndex(i)
                break
        self._cl.addWidget(self._locale_combo)

    def _build_api_key(self):
        self._cl.addWidget(_section_header(i18n.t("settings.api_key")))
        self._cl.addWidget(_lbl(i18n.t("settings.api_key_desc"), 11,
                                color=COLORS["text_dim"]))
        row = QHBoxLayout()
        row.setSpacing(8)
        current_key = self._settings.get("steamgriddb_key", "")
        self._key_entry = _entry(current_key, "xxxxxxxx…", password=True)
        row.addWidget(self._key_entry)

        eye = _ghost_btn(i18n.t("settings.show_key"),
                         command=self._toggle_key_visibility, width=90)
        self._eye_btn = eye
        row.addWidget(eye)
        row.addStretch()
        self._cl.addLayout(row)

        self._key_status = _lbl(
            i18n.t("settings.key_saved") if current_key else i18n.t("settings.key_missing"),
            11, color=COLORS["green"] if current_key else COLORS["gold"])
        self._cl.addWidget(self._key_status)

    def _build_country(self):
        self._cl.addWidget(_section_header(i18n.t("settings.currency_section")))
        self._cl.addWidget(_lbl(i18n.t("settings.currency_desc"), 11,
                                color=COLORS["text_dim"]))

        countries = [
            "mx — MXN", "us — USD", "ar — ARS", "br — BRL",
            "es — EUR", "gb — GBP", "de — EUR", "fr — EUR",
            "jp — JPY", "au — AUD", "ca — CAD", "ru — RUB",
            "tr — TRY", "cn — CNY", "in — INR", "nz — NZD",
            "no — NOK", "pl — PLN", "ch — CHF", "kr — KRW",
            "hk — HKD", "sg — SGD", "th — THB", "ua — UAH",
            "kz — KZT", "cl — CLP", "co — COP", "pe — PEN",
        ]
        self._country_combo = QComboBox()
        self._country_combo.setFixedHeight(36)
        self._country_combo.setFixedWidth(280)
        self._country_combo.setStyleSheet(self._combo_style())
        self._country_combo.addItems(countries)
        current = self._settings.get("country", "mx")
        for i, c in enumerate(countries):
            if c.startswith(current):
                self._country_combo.setCurrentIndex(i)
                break
        self._cl.addWidget(self._country_combo)

        # ── Timezone ──────────────────────────────────────────────────────────
        self._cl.addWidget(_section_header(i18n.t("settings.timezone")))
        self._cl.addWidget(_lbl(i18n.t("settings.timezone_desc"), 11,
                                color=COLORS["text_dim"]))
        self._tz_combo = QComboBox()
        self._tz_combo.setFixedHeight(36)
        self._tz_combo.setFixedWidth(180)
        self._tz_combo.setStyleSheet(self._combo_style())
        self._tz_combo.addItems(GMT_OPTIONS)
        current_tz = self._settings.get("timezone", "GMT-6")
        tz_idx = next((i for i, t in enumerate(GMT_OPTIONS)
                       if t == current_tz), GMT_OPTIONS.index("GMT-6"))
        self._tz_combo.setCurrentIndex(tz_idx)
        self._cl.addWidget(self._tz_combo)

        # Compare regions
        self._cl.addWidget(_section_header(i18n.t("settings.compare_regions")))
        self._cl.addWidget(_lbl(i18n.t("settings.compare_regions_desc"), 11,
                                color=COLORS["text_dim"]))

        # All available regions for comparison
        ALL_REGIONS = [
            "mx", "us", "ar", "br", "es", "gb", "de", "fr",
            "jp", "au", "ca", "ru", "tr", "cn", "in",
        ]
        saved_compare = self._settings.get("compare_regions", ["us", "ar", "br"])

        grid_w = QWidget(); grid_w.setStyleSheet("background:transparent;")
        from PySide6.QtWidgets import QGridLayout, QCheckBox
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 4, 0, 4); grid.setSpacing(6)
        self._region_checks: dict[str, QCheckBox] = {}
        for i, cc in enumerate(ALL_REGIONS):
            cb = QCheckBox(i18n.t(f"regions.{cc}"))
            cb.setChecked(cc in saved_compare)
            cb.setStyleSheet(f"""
                QCheckBox {{ color:{COLORS['text']}; background:transparent;
                    font-family:'Space Mono'; font-size:11px; }}
                QCheckBox::indicator {{ width:16px; height:16px; }}
            """)
            self._region_checks[cc] = cb
            grid.addWidget(cb, i // 5, i % 5)
        self._cl.addWidget(grid_w)

    def _build_token(self):
        self._cl.addWidget(_section_header(i18n.t("settings.pimp_account")))
        self._cl.addWidget(_lbl(
            i18n.t("settings.pimp_desc"),
            11, color=COLORS["text_dim"], wrap=True))

        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        current_token = self._settings.get("steamkustom_token", "")
        self._sk_token_entry = _entry(
            current_token, i18n.t("settings.pimp_placeholder"),
            password=bool(current_token), width=340)
        token_row.addWidget(self._sk_token_entry)

        status_text  = i18n.t("settings.pimp_token_saved") if current_token else ""
        status_color = COLORS["green"] if current_token else COLORS["text_dim"]
        self._sk_status_lbl = _lbl(status_text, 11, color=status_color)
        token_row.addWidget(self._sk_status_lbl)
        token_row.addStretch()
        self._cl.addLayout(token_row)

        verify_row = QHBoxLayout()
        self._verify_btn = _ghost_btn(i18n.t("settings.pimp_verify_btn"),
                                      command=self._verify_sk_token, width=130)
        verify_row.addWidget(self._verify_btn)
        verify_row.addStretch()
        self._cl.addLayout(verify_row)
        self._cl.addWidget(_lbl(
            i18n.t("settings.pimp_hint"),
            9, color=COLORS["text_dim"]))

        # Auto-verify on open
        if current_token:
            QTimer.singleShot(500, lambda: self._bg_verify(current_token, auto=True))

    def _build_services(self):
        self._cl.addWidget(_section_header(i18n.t("settings.connected_services")))

        svc_frame = QFrame()
        svc_frame.setStyleSheet(f"""
            QFrame {{
                background:{COLORS['card']};
                border:1px solid {COLORS['border']};
                border-radius:8px;
            }}
        """)
        sl = QVBoxLayout(svc_frame)
        sl.setContentsMargins(16, 12, 16, 12)
        sl.setSpacing(4)

        self._steam_lbl = _lbl(
            i18n.t("settings.steam_not_linked"),
            12, color=COLORS["text_dim"])
        self._drive_lbl = _lbl(
            i18n.t("settings.drive_not_linked"),
            12, color=COLORS["text_dim"])
        sl.addWidget(self._steam_lbl)
        sl.addWidget(self._drive_lbl)
        self._cl.addWidget(svc_frame)

        self._cl.addWidget(_lbl(
            i18n.t("settings.connect_hint"),
            10, color=COLORS["text_dim"]))

        sync_row = QHBoxLayout()
        self._sync_btn = _ghost_btn(
            i18n.t("settings.sync_btn"),
            command=self._sync_wishlist, width=210)
        sync_row.addWidget(self._sync_btn)
        self._sync_status_lbl = _lbl("", 11, color=COLORS["text_dim"])
        sync_row.addWidget(self._sync_status_lbl)
        sync_row.addStretch()
        self._cl.addLayout(sync_row)

    def _build_save(self):
        self._cl.addSpacing(24)
        save_btn = QPushButton(i18n.t("settings.save_settings"))
        save_btn.setFixedSize(180, 38)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background:{COLORS['blue']}; color:#0a1929;
                border:none; border-radius:6px;
                font-family:'Space Mono'; font-size:13px; font-weight:bold;
            }}
            QPushButton:hover {{ background:#4fa8d8; }}
        """)
        save_btn.clicked.connect(self._save)
        self._cl.addWidget(save_btn)

        self._feedback = _lbl("", 11, color=COLORS["green"])
        self._cl.addWidget(self._feedback)
        self._cl.addStretch()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _toggle_key_visibility(self):
        self._key_visible = not self._key_visible
        self._key_entry.setEchoMode(
            QLineEdit.EchoMode.Normal if self._key_visible
            else QLineEdit.EchoMode.Password)
        self._eye_btn.setText(
            i18n.t("settings.hide_key") if self._key_visible
            else i18n.t("settings.show_key"))

    def _bg_verify(self, token: str, auto: bool = False):
        def _work():
            try:
                from services.steamkustom_auth import verify_token
                user = verify_token(token)
            except Exception:
                user = None
            self._sig.verify_done.emit(bool(user), user)
        threading.Thread(target=_work, daemon=True).start()

    def _verify_sk_token(self):
        token = self._sk_token_entry.text().strip()
        if not token:
            self._sk_status_lbl.setText(i18n.t("settings.enter_token_first"))
            self._sk_status_lbl.setStyleSheet(
                f"color:{COLORS['gold']}; background:transparent;")
            return
        self._sk_status_lbl.setText(i18n.t("settings.verifying"))
        self._sk_status_lbl.setStyleSheet(
            f"color:{COLORS['blue']}; background:transparent;")
        self._verify_btn.setEnabled(False)
        self._bg_verify(token)

    def _on_verify_done(self, ok: bool, user):
        self._verify_btn.setEnabled(True)
        if ok and user:
            token = self._sk_token_entry.text().strip()
            from ui.settings_loader import save_settings as _save
            s = load_settings()
            s["steamkustom_token"] = token
            if user.get("steam_id"):
                s["steam_id64"] = user["steam_id"]
            _save(s)
            self._settings["steamkustom_token"] = token
            self._sk_token_entry.setEchoMode(QLineEdit.EchoMode.Password)
            name = user.get("username", i18n.t("settings.verified_as").replace("{name}", ""))
            self._sk_status_lbl.setText(i18n.t("settings.verified_as").format(name=name))
            self._sk_status_lbl.setStyleSheet(
                f"color:{COLORS['green']}; background:transparent;")

            steam_name = user.get("steam_name") or user.get("steam_id") or ""
            has_drive  = bool(user.get("has_google"))
            self._steam_lbl.setText(
                i18n.t('settings.steam_linked').format(name=steam_name) if steam_name else i18n.t('settings.steam_not_linked_lbl'))
            self._steam_lbl.setStyleSheet(
                f"color:{COLORS['green'] if steam_name else COLORS['text_dim']};"
                f" background:transparent;")
            self._drive_lbl.setText(
                i18n.t('settings.drive_linked') if has_drive else i18n.t('settings.drive_not_linked_lbl'))
            self._drive_lbl.setStyleSheet(
                f"color:{COLORS['green'] if has_drive else COLORS['text_dim']};"
                f" background:transparent;")
        else:
            self._sk_status_lbl.setText(i18n.t("settings.invalid_token"))
            self._sk_status_lbl.setStyleSheet(
                f"color:{COLORS['red']}; background:transparent;")

    def _sync_wishlist(self):
        self._sync_btn.setEnabled(False)
        self._sync_btn.setText(i18n.t("settings.syncing"))
        self._sync_status_lbl.setText("")

        def _set_status(msg: str, color: str = COLORS["text_dim"]):
            """Thread-safe status update."""
            QTimer.singleShot(0, lambda m=msg, c=color: (
                self._sync_status_lbl.setText(m),
                self._sync_status_lbl.setStyleSheet(
                    f"color:{c}; background:transparent;")
            ))

        _done_called = [False]

        def _done(msg: str, color: str):
            if _done_called[0]:
                return
            _done_called[0] = True
            self._sync_btn.setEnabled(True)
            self._sync_btn.setText(i18n.t("settings.sync_btn"))
            _set_status(msg, color)

        def _work():
            try:
                from services.steamkustom_auth import get_token, verify_token, get_steam_api_key
                from services.steam_wishlist import import_wishlist
                token = get_token()
                if not token:
                    QTimer.singleShot(0, lambda: _done(
                        i18n.t("settings.no_token"), COLORS["gold"]))
                    return

                _set_status(i18n.t("settings.verifying_token"))
                user = verify_token(token)
                if not user or not user.get("steam_id"):
                    QTimer.singleShot(0, lambda: _done(
                        i18n.t("settings.steam_not_connected"),
                        COLORS["gold"]))
                    return

                _set_status(i18n.t("settings.getting_api_key"))
                api_key = get_steam_api_key(token)
                if not api_key:
                    QTimer.singleShot(0, lambda: _done(
                        i18n.t("settings.api_key_unavailable"), COLORS["red"]))
                    return

                _set_status(i18n.t("settings.fetching_wishlist"))
                total_done = [0]

                def on_progress(current, total, app_id):
                    total_done[0] = current
                    if current % 5 == 0 or current == total:
                        _set_status(
                            i18n.t("settings.fetching_details").format(current=current, total=total),
                            COLORS["blue"])

                result = import_wishlist(
                    user["steam_id"], api_key,
                    on_progress=on_progress)

                added   = result.get("added", 0)
                skipped = result.get("skipped", 0)
                errors  = result.get("errors", 0)

                if added == 0:
                    QTimer.singleShot(0, lambda: _done(
                        i18n.t("settings.already_up_to_date").format(skipped=skipped),
                        COLORS["green"]))
                    return

                # Download covers for newly added games
                _set_status(i18n.t("settings.added_downloading").format(added=added),
                            COLORS["green"])

                def _covers_done(downloaded, failed):
                    msg = i18n.t("settings.added_covers_done").format(added=added, downloaded=downloaded)
                    if failed:
                        msg += i18n.t("settings.covers_failed").format(failed=failed)
                    QTimer.singleShot(0, lambda m=msg: _done(m, COLORS["green"]))

                # Only download covers for newly added games
                covers_started = [False]
                try:
                    import data.repository as repo
                    from services.steamgriddb import download_all_missing
                    from ui.settings_loader import get_settings
                    settings = get_settings()
                    api_key_sgdb = settings.get("steamgriddb_key", "")
                    all_games = repo.get_all()
                    covers_started[0] = True
                    download_all_missing(
                        all_games,
                        api_key_sgdb,
                        on_progress=lambda cur, tot, name: _set_status(
                            i18n.t("settings.downloading_covers").format(cur=cur, tot=tot, name=name[:20]),
                            COLORS["blue"]),
                        on_done=_covers_done,
                        max_workers=4,
                    )
                except Exception as e:
                    print(f"[Sync] Cover download error: {e}")
                    msg = i18n.t("settings.added_skipped").format(added=added, skipped=skipped)
                    QTimer.singleShot(0, lambda m=msg: _done(m, COLORS["green"]))
                    return
                # Safety net: if download_all_missing never calls on_done
                # (e.g. no missing covers, empty list), call _done directly.
                if covers_started[0]:
                    import time; time.sleep(0.1)
                    # download_all_missing is synchronous in most impls —
                    # if _done hasn't been called yet, fire it now.
                    # This is handled by _covers_done being called by on_done.
                    pass

            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda m=err: _done(m, COLORS["red"]))

        threading.Thread(target=_work, daemon=True).start()

    def _save(self):
        locale_str  = self._locale_combo.currentText().split(" — ")[0]
        country_str = self._country_combo.currentText().split(" — ")[0]
        tz_str      = self._tz_combo.currentText() if hasattr(self, "_tz_combo") else "GMT-6"
        api_key     = self._key_entry.text().strip()

        old_country     = self._settings.get("country", "mx")
        country_changed = country_str != old_country
        locale_changed  = locale_str != i18n.current_locale()

        compare_regions = [cc for cc, cb in self._region_checks.items()
                            if cb.isChecked()] if hasattr(self, "_region_checks") else                            self._settings.get("compare_regions", ["us", "ar", "br"])
        s = {**load_settings(),
             "locale": locale_str,
             "steamgriddb_key": api_key,
             "country": country_str,
             "timezone": tz_str,
             "compare_regions": compare_regions}
        save_settings(s)
        self._settings = s

        self._key_status.setText(
            i18n.t("settings.key_saved") if api_key else i18n.t("settings.key_missing"))
        self._key_status.setStyleSheet(
            f"color:{COLORS['green'] if api_key else COLORS['gold']}; background:transparent;")

        if country_changed:
            self._feedback.setText(i18n.t("settings.refreshing", n="..."))
            self._feedback.setStyleSheet(
                f"color:{COLORS['blue']}; background:transparent;")

            def _set_feedback(txt: str, color: str = COLORS["blue"]):
                """Thread-safe feedback update — no-op if widget was destroyed."""
                def _upd():
                    try:
                        self._feedback.setText(txt)
                        self._feedback.setStyleSheet(
                            f"color:{color}; background:transparent;")
                    except RuntimeError:
                        pass  # widget already destroyed (locale change)
                QTimer.singleShot(0, _upd)

            def _refresh():
                import services.steam_api as steam_api
                import data.repository as repo_mod
                games = repo_mod.get_all()
                total = len(games)
                for i, game in enumerate(games, 1):
                    # Live progress: "Actualizando 3/12…"
                    _set_feedback(
                        i18n.t("settings.refreshing", n=f"{i}/{total}"))
                    new_price = steam_api.refresh_price(game.app_id, country=country_str)
                    if new_price:
                        game.price = new_price
                        repo_mod.update(game)
                # Clear price cache so new currency prices are loaded fresh
                try:
                    from services.steam_api import clear_price_cache
                    clear_price_cache()
                except Exception:
                    pass

                if locale_changed:
                    i18n.load_locale(locale_str)
                    QTimer.singleShot(0, self.on_locale_change)
                else:
                    _set_feedback(
                        i18n.t("settings.refresh_done", n=total),
                        COLORS["green"])
                    # Force wishlist/dashboard refresh with new currency
                    QTimer.singleShot(200, self.on_locale_change)
                    QTimer.singleShot(4000, lambda: _set_feedback(""))

            threading.Thread(target=_refresh, daemon=True).start()

        elif locale_changed:
            i18n.load_locale(locale_str)
            self.on_locale_change()
        else:
            self._feedback.setText(i18n.t("settings.saved"))
            self._feedback.setStyleSheet(
                f"color:{COLORS['green']}; background:transparent;")
            QTimer.singleShot(3000, lambda: self._feedback.setText(""))

    # ── Style helpers ─────────────────────────────────────────────────────────

    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background:{COLORS['card']}; color:{COLORS['text']};
                border:1px solid {COLORS['border']}; border-radius:6px;
                padding:0 10px; font-family:'Space Mono'; font-size:11px;
                min-height:36px;
            }}
            QComboBox::drop-down {{ border:none; width:24px; }}
            QComboBox QAbstractItemView {{
                background:{COLORS['panel']}; color:{COLORS['text']};
                border:1px solid {COLORS['border']};
                selection-background-color:{COLORS['card_hover']};
            }}
        """


# ── Stubs for removed panels (keep imports working) ───────────────────────────

class SyncPanel(QFrame):
    def __init__(self, *a, **kw):
        super().__init__()

class SteamConnectPanel(QFrame):
    def __init__(self, *a, **kw):
        super().__init__()