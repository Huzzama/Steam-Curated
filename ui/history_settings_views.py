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


# ── settings helpers ──────────────────────────────────────────────────────────

_DEFAULTS = {
    "locale":            "es",
    "steamgriddb_key":   "",
    "country":           "mx",
    "steam_id64":        "",
    "steamkustom_token": "",
}


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
        hb.addWidget(_lbl(i18n.t("history.title"), 16, bold=True))
        hb.addWidget(_lbl(i18n.t("history.subtitle"), 11, color=COLORS["text_dim"]))
        hb.addStretch()
        root.addWidget(header)

        # Scroll
        self._content = QWidget()
        self._content.setStyleSheet(f"background:{COLORS['bg']};")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(16, 10, 16, 10)
        self._content_lay.setSpacing(0)

        self._empty_lbl = _lbl(i18n.t("history.empty"), 13,
                                color=COLORS["text_dim"])
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.hide()
        self._content_lay.addWidget(self._empty_lbl)
        self._content_lay.addStretch()

        root.addWidget(_scroll_area(self._content), 1)

        # Pre-build pool
        self._month_labels: list[QLabel] = [
            _lbl("", 12, bold=True, color=COLORS["blue"]) for _ in range(12)
        ]
        self._row_pool: list[tuple] = []
        for _ in range(MAX_HISTORY_ROWS):
            row = QFrame()
            row.setStyleSheet(f"""
                QFrame {{
                    background:{COLORS['card']};
                    border:1px solid {COLORS['border']};
                    border-radius:8px;
                }}
                QFrame:hover {{ border-color:{COLORS['blue']}44; }}
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
            info.setStyleSheet("background:transparent;")
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
                genre = game.genre.split(",")[0] if game.genre else "—"
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
        self._cl.addWidget(_section_header("PimpMySteam Account"))
        self._cl.addWidget(_lbl(
            "Generate a token at pimpmysteam.com → Settings → Apps.\n"
            "Paste it here to enable Drive sync and Steam wishlist import.",
            11, color=COLORS["text_dim"], wrap=True))

        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        current_token = self._settings.get("steamkustom_token", "")
        self._sk_token_entry = _entry(
            current_token, "Paste your app token here…",
            password=bool(current_token), width=340)
        token_row.addWidget(self._sk_token_entry)

        status_text  = "✓ Token saved" if current_token else ""
        status_color = COLORS["green"] if current_token else COLORS["text_dim"]
        self._sk_status_lbl = _lbl(status_text, 11, color=status_color)
        token_row.addWidget(self._sk_status_lbl)
        token_row.addStretch()
        self._cl.addLayout(token_row)

        verify_row = QHBoxLayout()
        self._verify_btn = _ghost_btn("Verify Token",
                                      command=self._verify_sk_token, width=130)
        verify_row.addWidget(self._verify_btn)
        verify_row.addStretch()
        self._cl.addLayout(verify_row)
        self._cl.addWidget(_lbl(
            "pimpmysteam.com → Settings → Apps → Generate Token",
            9, color=COLORS["text_dim"]))

        # Auto-verify on open
        if current_token:
            QTimer.singleShot(500, lambda: self._bg_verify(current_token, auto=True))

    def _build_services(self):
        self._cl.addWidget(_section_header("Connected Services"))

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
            "🎮  Steam — not linked (link at pimpmysteam.com)",
            12, color=COLORS["text_dim"])
        self._drive_lbl = _lbl(
            "☁  Google Drive — not linked (link at pimpmysteam.com)",
            12, color=COLORS["text_dim"])
        sl.addWidget(self._steam_lbl)
        sl.addWidget(self._drive_lbl)
        self._cl.addWidget(svc_frame)

        self._cl.addWidget(_lbl(
            "Connect Steam and Google Drive at pimpmysteam.com → Settings → Connections",
            10, color=COLORS["text_dim"]))

        sync_row = QHBoxLayout()
        self._sync_btn = _ghost_btn(
            "⟳  Sync Wishlist from Steam",
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
            self._sk_status_lbl.setText("Enter a token first")
            self._sk_status_lbl.setStyleSheet(
                f"color:{COLORS['gold']}; background:transparent;")
            return
        self._sk_status_lbl.setText("Verifying…")
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
            name = user.get("username", "Connected")
            self._sk_status_lbl.setText(f"✓ {name}")
            self._sk_status_lbl.setStyleSheet(
                f"color:{COLORS['green']}; background:transparent;")

            steam_name = user.get("steam_name") or user.get("steam_id") or ""
            has_drive  = bool(user.get("has_google"))
            self._steam_lbl.setText(
                f"🎮  Steam — {'✓ ' + steam_name if steam_name else 'not linked'}")
            self._steam_lbl.setStyleSheet(
                f"color:{COLORS['green'] if steam_name else COLORS['text_dim']};"
                f" background:transparent;")
            self._drive_lbl.setText(
                f"☁  Google Drive — {'✓ linked' if has_drive else 'not linked'}")
            self._drive_lbl.setStyleSheet(
                f"color:{COLORS['green'] if has_drive else COLORS['text_dim']};"
                f" background:transparent;")
        else:
            self._sk_status_lbl.setText("✗ Invalid token — check pimpmysteam.com")
            self._sk_status_lbl.setStyleSheet(
                f"color:{COLORS['red']}; background:transparent;")

    def _sync_wishlist(self):
        self._sync_btn.setEnabled(False)
        self._sync_btn.setText("Syncing…")
        self._sync_status_lbl.setText("")

        def _done(msg: str, color: str):
            """Always called at end — re-enables button."""
            self._sync_status_lbl.setText(msg)
            self._sync_status_lbl.setStyleSheet(
                f"color:{color}; background:transparent;")
            self._sync_btn.setEnabled(True)
            self._sync_btn.setText("⟳  Sync Wishlist from Steam")

        def _work():
            try:
                from services.steamkustom_auth import get_token, verify_token, get_steam_api_key
                from services.steam_wishlist import import_wishlist
                token = get_token()
                if not token:
                    QTimer.singleShot(0, lambda: _done("No token — verify first", COLORS["gold"]))
                    return
                user = verify_token(token)
                if not user or not user.get("steam_id"):
                    QTimer.singleShot(0, lambda: _done(
                        "Steam not linked — connect at pimpmysteam.com", COLORS["gold"]))
                    return
                api_key = get_steam_api_key(token)
                if not api_key:
                    QTimer.singleShot(0, lambda: _done(
                        "Steam API key unavailable", COLORS["red"]))
                    return
                result = import_wishlist(user["steam_id"], api_key)
                msg = f"✓ {result.get('added',0)} new, {result.get('updated',0)} updated"
                QTimer.singleShot(0, lambda m=msg: _done(m, COLORS["green"]))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda m=err: _done(m, COLORS["red"]))

        threading.Thread(target=_work, daemon=True).start()

    def _save(self):
        locale_str  = self._locale_combo.currentText().split(" — ")[0]
        country_str = self._country_combo.currentText().split(" — ")[0]
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

            def _refresh():
                import services.steam_api as steam_api
                import data.repository as repo_mod
                games = repo_mod.get_all()
                for game in games:
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
                    QTimer.singleShot(0, lambda: self._feedback.setText(
                        i18n.t("settings.refresh_done", n=len(games))))
                    QTimer.singleShot(0, lambda: self._feedback.setStyleSheet(
                        f"color:{COLORS['green']}; background:transparent;"))
                    # Force wishlist/dashboard refresh with new currency
                    QTimer.singleShot(0, self.on_locale_change)

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