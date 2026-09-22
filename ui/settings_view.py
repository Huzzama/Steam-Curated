"""
Settings — account, sync, backup, preferences, API keys and about.

    SettingsView(parent, on_locale_change=..., on_data_changed=..., notify=...)
    view.refresh(force=False)     re-read settings.json / creds and re-render
    view.retranslate()            update visible strings in place

Every network call (token verification, wishlist import, Drive status and
transfers, cover download, IsThereAnyDeal test, price refresh after a
country change) goes through ui.async_bridge.run_async. Preferences save
the moment they change — there is no "Save" button.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QLabel, QMessageBox, QProgressBar, QSizePolicy,
                               QWidget)

import config
import i18n
import data.repository as repo
from services import steamkustom_auth as auth
from services._http import ApiError, Unreachable
from ui import icons
from ui.animations import clear_layout, shake
from ui.async_bridge import run_async
from ui.components import (Button, Card, Divider, ElidedLabel, FlowLayout, Pill, SectionHeader,
                           SubHeader, TextField, hbox, label, scroll_area, vbox)
from ui.format import money
from ui.settings_loader import get_settings, save_settings
from ui.theme import C, SP, repolish

CONTENT_MAX_WIDTH = 720
LABEL_WIDTH = 168

# (country code, currency) — the same list the previous Settings used
COUNTRIES: list[tuple[str, str]] = [
    ("mx", "MXN"), ("us", "USD"), ("ar", "ARS"), ("br", "BRL"), ("es", "EUR"), ("gb", "GBP"),
    ("de", "EUR"), ("fr", "EUR"), ("jp", "JPY"), ("au", "AUD"), ("ca", "CAD"), ("ru", "RUB"),
    ("tr", "TRY"), ("cn", "CNY"), ("in", "INR"), ("nz", "NZD"), ("no", "NOK"), ("pl", "PLN"),
    ("ch", "CHF"), ("kr", "KRW"), ("hk", "HKD"), ("sg", "SGD"), ("th", "THB"), ("ua", "UAH"),
    ("kz", "KZT"), ("cl", "CLP"), ("co", "COP"), ("pe", "PEN"),
]
CURRENCY_OF = dict(COUNTRIES)

GMT_OPTIONS = [
    "GMT-12", "GMT-11", "GMT-10", "GMT-9", "GMT-8", "GMT-7", "GMT-6", "GMT-5", "GMT-4",
    "GMT-3", "GMT-2", "GMT-1", "GMT+0", "GMT+1", "GMT+2", "GMT+3", "GMT+4", "GMT+5",
    "GMT+5:30", "GMT+6", "GMT+7", "GMT+8", "GMT+9", "GMT+10", "GMT+11", "GMT+12",
]

COMPARE_REGIONS = ["mx", "us", "ar", "br", "es", "gb", "de", "fr", "jp", "au", "ca", "ru",
                   "tr", "cn", "in"]
DEFAULT_COMPARE = ["us", "ar", "br"]

ITAD_KEYS_URL = "https://isthereanydeal.com/apps/my/"
ITAD_TEST_APP = "1245620"          # Elden Ring — exists in every region
APP_VERSION = getattr(config, "APP_VERSION", "2.0")


class _UserFacing(Exception):
    """An error whose message is already translated for the user."""


class SettingsView(QWidget):
    """Account · wishlist sync · Drive backup · preferences · API keys · about."""

    def __init__(self, parent=None, on_locale_change: Optional[Callable] = None,
                 on_data_changed: Optional[Callable] = None, notify: Optional[Callable] = None,
                 **_):
        super().__init__(parent)
        self._on_locale_change = on_locale_change or (lambda: None)
        self._on_data_changed = on_data_changed or (lambda: None)
        self._notify_dep = notify
        self._settings: dict = {}
        self._labels: list[tuple[QLabel, str]] = []      # (label, i18n key) for retranslate
        self._buttons: list[tuple[Button, str]] = []
        self._chips: dict[str, Button] = {}
        self._drive_status: Optional[dict] = None
        self._busy: set[str] = set()
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _tl(self, key: str, role: str = "dim", **kw) -> QLabel:
        """Translated label, registered for retranslate()."""
        l = label(i18n.t(key), role, **kw)
        self._labels.append((l, key))
        return l

    def _tb(self, key: str, **kw) -> Button:
        b = Button(i18n.t(key), **kw)
        self._buttons.append((b, key))
        return b

    def _section(self, title_key: str) -> Card:
        """SubHeader + Card appended to the column; returns the card."""
        head = SubHeader(i18n.t(title_key))
        self._labels.append((head.title, title_key))
        self._col.addWidget(head)
        card = Card(padding=SP["lg"], spacing=SP["md"])
        self._col.addWidget(card)
        return card

    @staticmethod
    def _field_row(lbl: QLabel, control: QWidget, stretch_control: bool = False):
        row = hbox(spacing=SP["md"])
        lbl.setFixedWidth(LABEL_WIDTH)
        row.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(control, 1 if stretch_control else 0)
        if not stretch_control:
            row.addStretch()
        return row

    @staticmethod
    def _combo(min_width: int = 260) -> QComboBox:
        cb = QComboBox()
        cb.setMinimumHeight(34)
        cb.setMinimumWidth(min_width)
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        return cb

    def _build(self) -> None:
        root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["xl"]), SP["lg"])
        self._header = SectionHeader(i18n.t("settings.title"), i18n.t("settings.subtitle"))
        self._labels += [(self._header.title, "settings.title"), (self._header.subtitle, "settings.subtitle")]
        root.addWidget(self._header)

        content = QWidget()
        outer = hbox(content, (0, 0, SP["sm"], 0), 0)
        column = QWidget()
        column.setMaximumWidth(CONTENT_MAX_WIDTH)
        column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._col = vbox(column, spacing=SP["sm"])
        outer.addWidget(column, 1)
        outer.addStretch(0)
        root.addWidget(scroll_area(content), 1)

        self._build_account()
        self._build_wishlist_sync()
        self._build_drive()
        self._build_preferences()
        self._build_api_keys()
        self._build_about()
        self._col.addStretch()

    # 1 ─ account
    def _build_account(self) -> None:
        self._acct_card = self._section("settings.account_section")

    def _render_account(self) -> None:
        body = self._acct_card.body
        clear_layout(body)
        t = i18n.t
        if auth.is_connected():
            row = hbox(spacing=SP["md"])
            ic = QLabel()
            ic.setPixmap(icons.pixmap("badge-check", C["green"], 22))
            row.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
            col = vbox(spacing=2)
            name_row = hbox(spacing=SP["sm"])
            name_row.addWidget(label(auth.get_username() or t("settings.account_connected"), "h2"))
            name_row.addWidget(Pill(t("settings.account_connected").upper(), "green"))
            name_row.addStretch()
            col.addLayout(name_row)
            sid = auth.get_steam_id()
            col.addWidget(label(f"{t('settings.steam_id')}  {sid}" if sid else t("settings.steam_not_linked_lbl"),
                                "mono", color=C["text_dim"]))
            row.addLayout(col, 1)
            row.addWidget(Button(t("settings.disconnect"), variant="danger", icon="log-out",
                                 on_click=self._disconnect), 0, Qt.AlignmentFlag.AlignVCenter)
            body.addLayout(row)
            return

        body.addWidget(label(t("settings.pimp_desc"), "dim", wrap=True))
        row = hbox(spacing=SP["sm"])
        self._token = TextField(t("settings.pimp_placeholder"), icon="key-round", password=True)
        self._token.returnPressed.connect(self._connect)
        self._token.textChanged.connect(lambda _t: self._set_account_error(""))
        row.addWidget(self._token, 1)
        self._connect_btn = Button(t("settings.connect"), variant="primary", icon="arrow-right",
                                   on_click=self._connect)
        row.addWidget(self._connect_btn)
        body.addLayout(row)
        self._acct_error = label("", "muted", color=C["red"], wrap=True)
        self._acct_error.hide()
        body.addWidget(self._acct_error)
        body.addWidget(label(t("settings.pimp_hint"), "muted"))

    # 2 ─ wishlist sync
    def _build_wishlist_sync(self) -> None:
        card = self._section("settings.wishlist_section")
        card.body.addWidget(self._tl("settings.wishlist_desc", "dim", wrap=True))
        row = hbox(spacing=SP["md"])
        self._sync_btn = self._tb("settings.sync_wishlist", icon="refresh", on_click=self._sync_wishlist)
        row.addWidget(self._sync_btn)
        self._sync_bar = QProgressBar()
        self._sync_bar.setFixedWidth(160)
        self._sync_bar.setTextVisible(False)
        self._sync_bar.hide()
        row.addWidget(self._sync_bar)
        self._sync_progress = label("", "mono", color=C["text_dim"])
        row.addWidget(self._sync_progress)
        row.addStretch()
        card.body.addLayout(row)
        self._sync_hint = self._tl("settings.sync_needs_account", "muted", wrap=True)
        card.body.addWidget(self._sync_hint)

    # 3 ─ drive
    def _build_drive(self) -> None:
        card = self._section("settings.drive_section")
        card.body.addWidget(self._tl("settings.drive_desc", "dim", wrap=True))
        status = hbox(spacing=SP["sm"])
        self._drive_icon = QLabel()
        status.addWidget(self._drive_icon)
        self._drive_label = label("", "body")
        status.addWidget(self._drive_label, 1)
        card.body.addLayout(status)
        row = hbox(spacing=SP["sm"])
        self._upload_btn = self._tb("settings.upload_now", icon="upload", on_click=self._upload)
        self._download_btn = self._tb("settings.download_now", icon="download", on_click=self._download)
        row.addWidget(self._upload_btn)
        row.addWidget(self._download_btn)
        row.addStretch()
        card.body.addLayout(row)

    # 4 ─ preferences
    def _build_preferences(self) -> None:
        card = self._section("settings.preferences")

        self._locale_combo = self._combo()
        for code, name in i18n.available_locales().items():
            self._locale_combo.addItem(name, code)
        self._locale_combo.currentIndexChanged.connect(self._on_locale)
        card.body.addLayout(self._field_row(self._tl("settings.language"), self._locale_combo))

        self._country_combo = self._combo()
        for code, cur in COUNTRIES:
            self._country_combo.addItem(f"{code.upper()}  ·  {cur}", code)
        self._country_combo.currentIndexChanged.connect(self._on_country)
        card.body.addLayout(self._field_row(self._tl("settings.country"), self._country_combo))
        self._price_progress = label("", "muted")
        self._price_progress.setContentsMargins(LABEL_WIDTH + SP["md"], 0, 0, 0)
        self._price_progress.hide()
        card.body.addWidget(self._price_progress)

        self._tz_combo = self._combo(160)
        for tz in GMT_OPTIONS:
            self._tz_combo.addItem(tz, tz)
        self._tz_combo.currentIndexChanged.connect(self._on_timezone)
        card.body.addLayout(self._field_row(self._tl("settings.timezone"), self._tz_combo))

        chips_box = QWidget()
        flow = FlowLayout(chips_box, SP["xs"], SP["xs"])
        for cc in COMPARE_REGIONS:
            b = Button(i18n.t(f"regions.{cc}"), variant="chip", on_click=lambda _=False, c=cc: self._toggle_region(c))
            b.setProperty("active", "false")
            self._chips[cc] = b
            flow.addWidget(b)
        regions_lbl = self._tl("settings.compare_regions", wrap=True)
        regions_lbl.setFixedWidth(LABEL_WIDTH)
        row = hbox(spacing=SP["md"])
        row.addWidget(regions_lbl, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(chips_box, 1)
        card.body.addLayout(row)
        desc = self._tl("settings.compare_regions_desc", "muted", wrap=True)
        desc.setContentsMargins(LABEL_WIDTH + SP["md"], 0, 0, 0)
        card.body.addWidget(desc)

    # 5 ─ api keys
    def _build_api_keys(self) -> None:
        card = self._section("settings.api_keys")

        card.body.addWidget(self._tl("settings.api_key", "body"))
        card.body.addWidget(self._tl("settings.sgdb_desc", "muted", wrap=True))
        row = hbox(spacing=SP["sm"])
        self._sgdb_key = TextField("", icon="key-round", password=True)
        self._sgdb_key.editingFinished.connect(lambda: self._save_key("steamgriddb_key", self._sgdb_key))
        row.addWidget(self._sgdb_key, 1)
        self._covers_btn = self._tb("settings.download_covers", icon="image", on_click=self._download_covers)
        row.addWidget(self._covers_btn)
        card.body.addLayout(row)

        card.body.addWidget(Divider())

        head = hbox(spacing=SP["sm"])
        head.addWidget(self._tl("settings.itad_key", "body"))
        head.addStretch()
        link = self._tb("settings.itad_link", variant="link", icon="external-link",
                        on_click=lambda: QDesktopServices.openUrl(QUrl(ITAD_KEYS_URL)))
        link.setToolTip(ITAD_KEYS_URL)
        head.addWidget(link)
        card.body.addLayout(head)
        card.body.addWidget(self._tl("settings.itad_desc", "muted", wrap=True))
        row = hbox(spacing=SP["sm"])
        self._itad_key = TextField("", icon="key-round", password=True)
        self._itad_key.editingFinished.connect(lambda: self._save_key("itad_key", self._itad_key))
        self._itad_key.textChanged.connect(lambda _t: self._itad_key.set_error(False))
        row.addWidget(self._itad_key, 1)
        self._itad_test_btn = self._tb("settings.test", icon="zap", on_click=self._test_itad)
        row.addWidget(self._itad_test_btn)
        card.body.addLayout(row)

    # 6 ─ about
    def _build_about(self) -> None:
        card = self._section("settings.about")
        name_row = hbox(spacing=SP["sm"])
        name_row.addWidget(label(config.APP_NAME, "h2"))
        name_row.addWidget(Pill(f"v{APP_VERSION}", "accent"))
        name_row.addStretch()
        card.body.addLayout(name_row)

        for key, path in (("settings.data_folder", config.BASE_DIR),
                          ("settings.logs_folder", config.BASE_DIR / "logs")):
            row = hbox(spacing=SP["md"])
            lbl = self._tl(key)
            lbl.setFixedWidth(LABEL_WIDTH)
            row.addWidget(lbl)
            value = ElidedLabel(str(path), "mono")
            value.setToolTip(str(path))
            row.addWidget(value, 1)
            row.addWidget(self._tb("settings.open_folder", variant="ghost", icon="folder-open",
                                   on_click=lambda _=False, p=path: self._open_folder(p)))
            card.body.addLayout(row)

    # ── shell contract ───────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> None:
        """Re-read settings + credentials and re-render every section."""
        self._settings = get_settings()
        self._render_account()
        self._update_sync_state()
        self._sync_prefs()
        self._sgdb_key.setText(self._settings.get("steamgriddb_key", "") or "")
        self._itad_key.setText(self._settings.get("itad_key", "") or "")
        if force or self._drive_status is None:
            self._check_drive()
        else:
            self._render_drive()

    def retranslate(self) -> None:
        t = i18n.t
        for lbl, key in self._labels:
            lbl.setText(t(key))
        for btn, key in self._buttons:
            btn.setText(t(key))
        for cc, chip in self._chips.items():
            chip.setText(t(f"regions.{cc}"))
        self._render_account()
        self._render_drive()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _notify(self, message: str, tone: str = "info") -> None:
        if self._notify_dep:
            self._notify_dep(message, tone)
            return
        win = self.window()
        if hasattr(win, "notify"):
            win.notify(message, tone)

    def _refresh_shell_account(self) -> None:
        """Sidebar shows the account name — ask the shell to re-read it."""
        win = self.window()
        fn = getattr(win, "_refresh_account", None)
        if callable(fn):
            fn()

    @staticmethod
    def _error_text(e: Exception) -> str:
        if isinstance(e, _UserFacing):
            return str(e)
        if isinstance(e, ApiError):
            if e.status in (401, 403):
                return i18n.t("settings.invalid_token")
            return i18n.t("settings.api_error", status=e.status)
        if isinstance(e, Unreachable):
            return i18n.t("settings.unreachable")
        try:
            from services.library_api import LibraryError
            if isinstance(e, LibraryError):
                return str(e)
        except ImportError:
            pass
        return str(e) or type(e).__name__

    def _country(self) -> str:
        return (self._settings.get("country") or get_settings().get("country") or "us").lower()

    @staticmethod
    def _open_folder(path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ── account ──────────────────────────────────────────────────────────────

    def _set_account_error(self, text: str) -> None:
        if not hasattr(self, "_acct_error"):
            return
        self._acct_error.setText(text)
        self._acct_error.setVisible(bool(text))
        self._token.set_error(bool(text))

    def _connect(self) -> None:
        if "connect" in self._busy:
            return
        token = self._token.text().strip()
        if not token:
            self._set_account_error(i18n.t("settings.enter_token_first"))
            shake(self._token)
            return
        self._busy.add("connect")
        self._set_account_error("")
        self._connect_btn.set_loading(True, i18n.t("settings.verifying"))

        def on_done(result):
            self._busy.discard("connect")
            if isinstance(result, Exception):
                self._connect_btn.set_loading(False)
                self._set_account_error(self._error_text(result))
                shake(self._token)
                return
            auth.save_account(token, result if isinstance(result, dict) else None)
            name = auth.get_username() or (result.get("username") if isinstance(result, dict) else "")
            self._notify(i18n.t("settings.connected_as", name=name or i18n.t("settings.account_connected")), "success")
            self._refresh_shell_account()
            self._drive_status = None
            self.refresh(force=True)

        run_async(self, lambda: auth.verify_token(token), on_done=on_done)

    def _disconnect(self) -> None:
        t = i18n.t
        answer = QMessageBox.question(self, t("settings.disconnect"), t("settings.disconnect_confirm"))
        if answer != QMessageBox.StandardButton.Yes:
            return
        auth.clear_token()
        try:
            from services.library_api import invalidate_cache
            invalidate_cache()
        except ImportError:
            pass
        self._notify(t("settings.disconnected"), "info")
        self._refresh_shell_account()
        self._drive_status = None
        self.refresh(force=True)

    # ── wishlist sync ────────────────────────────────────────────────────────

    def _update_sync_state(self) -> None:
        connected = auth.is_connected()
        self._sync_btn.setEnabled(connected and "sync" not in self._busy)
        self._sync_hint.setVisible(not connected)

    def _sync_wishlist(self) -> None:
        if "sync" in self._busy or not auth.is_connected():
            return
        from services.steam_wishlist import import_wishlist
        t = i18n.t
        country = self._country()
        self._busy.add("sync")
        self._sync_btn.set_loading(True, t("settings.syncing"))
        self._sync_bar.setRange(0, 0)
        self._sync_bar.show()
        self._sync_progress.setText(t("settings.fetching_wishlist"))

        def work(progress):
            sid = auth.get_steam_id()
            if not sid:
                raise _UserFacing(t("settings.sync_no_steam"))
            try:
                return import_wishlist(sid, None, country,
                                       on_progress=lambda i, total, _app: progress((i, total)))
            except ApiError as e:
                if e.status == 404:
                    raise _UserFacing(t("settings.sync_no_steam")) from e
                raise

        def on_progress(p):
            cur, total = p
            self._sync_bar.setRange(0, max(total, 1))
            self._sync_bar.setValue(cur)
            self._sync_progress.setText(t("settings.sync_progress", cur=cur, total=total))

        def on_done(result):
            self._busy.discard("sync")
            self._sync_btn.set_loading(False)
            self._sync_bar.hide()
            self._sync_progress.setText("")
            self._update_sync_state()
            if isinstance(result, Exception):
                self._notify(t("settings.sync_failed", msg=self._error_text(result)), "error")
                return
            added = result.get("added", 0)
            skipped = result.get("skipped", 0)
            errors = result.get("errors", 0) + result.get("dropped", 0)
            if errors:
                self._notify(t("settings.sync_result_errors", added=added, skipped=skipped, errors=errors), "warning")
            else:
                self._notify(t("settings.sync_result", added=added, skipped=skipped), "success")
            self._on_data_changed()
            if added:
                self._download_covers()

        run_async(self, work, on_done=on_done, on_progress=on_progress)

    # ── drive ────────────────────────────────────────────────────────────────

    def _check_drive(self) -> None:
        if "drive_check" in self._busy:
            return
        from services import drive_sync
        self._busy.add("drive_check")
        self._drive_icon.setPixmap(icons.pixmap("loader-circle", C["text_dim"], 16))
        self._drive_label.setText(i18n.t("settings.drive_checking"))
        self._drive_label.setProperty("role", "dim")
        repolish(self._drive_label)
        self._upload_btn.setEnabled(False)
        self._download_btn.setEnabled(False)

        def on_done(result):
            self._busy.discard("drive_check")
            if isinstance(result, Exception):
                result = {"configured": False, "authenticated": False, "mode": "api"}
            self._drive_status = result
            self._render_drive()

        run_async(self, drive_sync.get_sync_status, on_done=on_done)

    def _render_drive(self) -> None:
        st = self._drive_status
        if st is None or "drive_check" in self._busy:
            return
        t = i18n.t
        ready = bool(st.get("configured")) and bool(st.get("authenticated"))
        if ready:
            icon, color = "cloud", C["green"]
            text = t("settings.drive_ready_api" if st.get("mode") == "api" else "settings.drive_ready_local")
        elif st.get("configured"):
            icon, color, text = "cloud-off", C["gold"], t("settings.drive_unlinked")
        else:
            icon, color, text = "cloud-off", C["text_muted"], t("settings.drive_unconfigured")
        self._drive_icon.setPixmap(icons.pixmap(icon, color, 16))
        self._drive_label.setText(text)
        self._drive_label.setProperty("role", "body" if ready else "dim")
        repolish(self._drive_label)
        busy = "drive_io" in self._busy
        self._upload_btn.setEnabled(ready and not busy)
        self._download_btn.setEnabled(ready and not busy)

    def _upload(self) -> None:
        self._drive_transfer("upload")

    def _download(self) -> None:
        self._drive_transfer("download")

    def _drive_transfer(self, kind: str) -> None:
        if "drive_io" in self._busy:
            return
        from services import drive_sync
        t = i18n.t
        btn = self._upload_btn if kind == "upload" else self._download_btn
        other = self._download_btn if kind == "upload" else self._upload_btn
        self._busy.add("drive_io")
        btn.set_loading(True)
        other.setEnabled(False)
        work = drive_sync.upload_all if kind == "upload" else drive_sync.download_all

        def on_done(result):
            self._busy.discard("drive_io")
            btn.set_loading(False)
            self._render_drive()
            if isinstance(result, Exception):
                self._notify(t("sync.error", msg=self._error_text(result)), "error")
                return
            errors = result.get("errors") or []
            n = result.get("uploaded" if kind == "upload" else "downloaded", 0)
            if errors:
                self._notify(t("sync.error", msg=errors[0]), "error")
            elif n == 0:
                self._notify(t("settings.drive_nothing"), "info")
            else:
                self._notify(t("sync.upload_done" if kind == "upload" else "sync.download_done", n=n), "success")
            if kind == "download" and n:
                invalidate = getattr(repo, "_invalidate", None)
                if callable(invalidate):
                    invalidate()
                try:
                    import data.purchase_repository as purchases
                    purchases.invalidate()
                except (ImportError, AttributeError):
                    pass
                self._on_data_changed()

        run_async(self, lambda: work(), on_done=on_done)

    # ── preferences ──────────────────────────────────────────────────────────

    def _sync_prefs(self) -> None:
        """Push settings.json into the controls without firing change handlers."""
        s = self._settings
        for combo, value in ((self._locale_combo, i18n.current_locale()),
                             (self._country_combo, (s.get("country") or "mx").lower()),
                             (self._tz_combo, s.get("timezone") or "GMT-6")):
            combo.blockSignals(True)
            idx = combo.findData(value)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)
        selected = set(s.get("compare_regions") if isinstance(s.get("compare_regions"), list) else DEFAULT_COMPARE)
        for cc, chip in self._chips.items():
            active = "true" if cc in selected else "false"
            if chip.property("active") != active:
                chip.setProperty("active", active)
                repolish(chip)

    def _on_locale(self, _idx: int) -> None:
        code = self._locale_combo.currentData()
        if not code or code == i18n.current_locale():
            return
        i18n.load_locale(code)
        save_settings({"locale": code})
        self._settings["locale"] = code
        self._on_locale_change()

    def _on_timezone(self, _idx: int) -> None:
        tz = self._tz_combo.currentData()
        if not tz or tz == self._settings.get("timezone"):
            return
        save_settings({"timezone": tz})
        self._settings["timezone"] = tz
        self._notify(i18n.t("settings.timezone_saved"), "success")

    def _toggle_region(self, cc: str) -> None:
        chip = self._chips[cc]
        active = chip.property("active") != "true"
        chip.setProperty("active", "true" if active else "false")
        repolish(chip)
        regions = [c for c, b in self._chips.items() if b.property("active") == "true"]
        save_settings({"compare_regions": regions})
        self._settings["compare_regions"] = regions
        self._notify(i18n.t("settings.regions_saved"), "success")

    def _on_country(self, _idx: int) -> None:
        cc = self._country_combo.currentData()
        if not cc or cc == self._settings.get("country") or "prices" in self._busy:
            return
        save_settings({"country": cc})
        self._settings["country"] = cc
        games = repo.get_all()
        if not games:
            self._notify(i18n.t("settings.saved"), "success")
            self._on_locale_change()
            return
        from services.steam_api import bulk_refresh_prices, clear_price_cache
        t = i18n.t
        self._busy.add("prices")
        self._country_combo.setEnabled(False)
        self._price_progress.setText(t("settings.country_saved", n=len(games)))
        self._price_progress.show()

        def work(progress):
            done = threading.Event()
            box: dict = {}

            def _done(updated, unchanged, failed):
                box["r"] = (updated, unchanged, failed)
                done.set()

            bulk_refresh_prices(games, country=cc,
                                on_progress=lambda c, total, _n: progress((c, total)),
                                on_done=_done, max_workers=6)
            done.wait()
            try:
                clear_price_cache()
            except Exception:  # noqa: BLE001
                pass
            return box["r"]

        def on_progress(p):
            cur, total = p
            self._price_progress.setText(t("settings.refreshing", n=f"{cur}/{total}"))

        def on_done(result):
            self._busy.discard("prices")
            self._country_combo.setEnabled(True)
            self._price_progress.hide()
            if isinstance(result, Exception):
                self._notify(t("settings.prices_refresh_failed", msg=self._error_text(result)), "error")
            else:
                self._notify(t("settings.prices_refreshed", n=result[0]), "success")
            self._on_locale_change()

        run_async(self, work, on_done=on_done, on_progress=on_progress)

    # ── api keys ─────────────────────────────────────────────────────────────

    def _save_key(self, key: str, field: TextField) -> None:
        value = field.text().strip()
        if value == (self._settings.get(key) or ""):
            return
        save_settings({key: value})
        self._settings[key] = value
        self._notify(i18n.t("settings.key_saved"), "success")

    def _download_covers(self) -> None:
        if "covers" in self._busy:
            return
        from services.steamgriddb import cover_exists, download_all_missing
        t = i18n.t
        games = repo.get_all()
        missing = [g for g in games if not cover_exists(g.app_id)]
        if not missing:
            self._notify(t("settings.covers_none"), "info")
            return
        api_key = self._sgdb_key.text().strip()
        self._busy.add("covers")
        self._covers_btn.set_loading(True, t("settings.covers_progress", cur=0, total=len(missing)))

        def work(progress):
            done = threading.Event()
            box: dict = {}

            def _done(downloaded, failed):
                box["r"] = (downloaded, failed)
                done.set()

            download_all_missing(games, api_key, on_progress=lambda c, total, _n: progress((c, total)),
                                 on_done=_done)
            done.wait()
            return box["r"]

        def on_progress(p):
            cur, total = p
            self._covers_btn.setText(t("settings.covers_progress", cur=cur, total=total))

        def on_done(result):
            self._busy.discard("covers")
            self._covers_btn.set_loading(False)
            if isinstance(result, Exception):
                self._notify(t("settings.covers_failed", msg=self._error_text(result)), "error")
                return
            downloaded, failed = result
            if failed:
                self._notify(t("settings.covers_done_errors", n=downloaded, fail=failed), "warning")
            else:
                self._notify(t("settings.covers_done", n=downloaded), "success")
            self._on_data_changed()

        run_async(self, work, on_done=on_done, on_progress=on_progress)

    def _test_itad(self) -> None:
        if "itad" in self._busy:
            return
        from services import price_history
        t = i18n.t
        key = self._itad_key.text().strip()
        if not key:
            self._itad_key.set_error(True)
            shake(self._itad_key)
            self._notify(t("settings.itad_missing"), "warning")
            return
        self._save_key("itad_key", self._itad_key)
        country = self._country()
        self._busy.add("itad")
        self._itad_test_btn.set_loading(True)

        def on_done(result):
            self._busy.discard("itad")
            self._itad_test_btn.set_loading(False)
            if isinstance(result, Exception):
                self._notify(t("settings.itad_error", msg=self._error_text(result)), "error")
                return
            if result is None or not getattr(result, "all_time_low", 0):
                self._notify(t("settings.itad_no_data"), "warning")
                return
            price = money(result.all_time_low, CURRENCY_OF.get(country, "USD"))
            self._notify(t("settings.itad_ok", price=price), "success")
            self._fill_history(country)

        run_async(self, lambda: price_history.get_price_history(ITAD_TEST_APP, country.upper(), key=key, force=True),
                  on_done=on_done)

    def _fill_history(self, country: str) -> None:
        """Pull all-time lows for the whole wishlist right after a key is verified."""
        if "history" in self._busy:
            return
        from services import price_history
        import data.repository as repo
        t = i18n.t
        self._busy.add("history")

        def work():
            games = [g for g in repo.get_all() if g.app_id]
            hists = price_history.get_price_histories(games, country.upper(), force=True)
            changed = []
            for g in games:
                merged = price_history.merge(g.price_history, hists.get(str(g.app_id)))
                if merged is not None and merged != g.price_history:
                    g.price_history = merged
                    changed.append(g)
            if changed:
                repo.update_many(changed)
            return len(changed), len(games)

        def on_done(result):
            self._busy.discard("history")
            if isinstance(result, Exception):
                self._notify(t("settings.history_failed", msg=self._error_text(result)), "error")
                return
            n, total = result
            self._notify(t("settings.history_done", n=n, total=total), "success")
            if n:
                self._on_data_changed()

        run_async(self, work, on_done=on_done)
