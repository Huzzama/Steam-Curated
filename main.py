import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import i18n
from ui.settings_loader import load_settings


import logging

log = logging.getLogger("curator")


def _setup_logging():
    """Console + rotating file log (the packaged app has no console)."""
    from logging.handlers import RotatingFileHandler
    from config import BASE_DIR
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    sh = logging.StreamHandler(); sh.setFormatter(fmt); root.addHandler(sh)
    try:
        (BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(BASE_DIR / "logs" / "curator.log",
                                 maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt); root.addHandler(fh)
    except OSError:
        pass


def _auto_sync_drive_startup():
    """Download wishlist/purchases from Drive — entirely off the GUI thread
    (is_authenticated() is a network call; it used to block startup for 10 s)."""
    import threading

    def _work():
        try:
            from services.drive_sync import is_configured, is_authenticated, download_all
            if is_configured() and is_authenticated():
                result = download_all()
                if result["downloaded"] > 0:
                    log.info("Drive: synced %d file(s) on startup", result["downloaded"])
        except Exception as e:  # noqa: BLE001
            log.info("Drive: startup sync skipped: %s", e)
    threading.Thread(target=_work, daemon=True).start()


def _auto_sync_drive_exit():
    """Upload on exit in a thread, waiting at most a few seconds so quitting
    never hangs the window."""
    import threading

    def _work():
        try:
            from services.drive_sync import is_configured, is_authenticated, upload_all
            if is_configured() and is_authenticated():
                upload_all()
        except Exception as e:  # noqa: BLE001
            log.info("Drive: exit sync skipped: %s", e)
    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=6)


def main():
    _setup_logging()
    settings = load_settings()
    i18n.load_locale(settings.get("locale", "es"))

    # Background Drive sync on startup
    _auto_sync_drive_startup()

    # ── macOS: must be set BEFORE QApplication is created ─────────────────────
    if sys.platform == "darwin":
        # Prevents Qt from fighting macOS over the menu bar and window focus,
        # which was causing secondary windows (Deals, Dashboard, etc.) to open
        # behind the main window or never become visible.
        import os
        os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from ui import theme
    from ui.app_window import AppWindow

    # ── macOS: AA_DontUseNativeMenuBar keeps the sidebar nav reliable ─────────
    if sys.platform == "darwin":
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)

    app = QApplication(sys.argv)
    app.setApplicationName("Steam Curator")
    theme.apply(app)          # fonts, palette, global stylesheet

    window = AppWindow()
    window.show()

    # macOS: explicitly activate the app so all views get proper focus/paint events.
    # Without this, views opened after launch (Deals, Dashboard, etc.) can appear
    # blank because macOS never delivered the initial expose event to them.
    if sys.platform == "darwin":
        app.setActiveWindow(window)

    # Refresh sale banners/dates in the background; re-render Deals on the
    # GUI thread when something changed (Signal — never QTimer from a thread).
    from PySide6.QtCore import QObject, Signal

    class _SalesSig(QObject):
        done = Signal(bool)
    sales_sig = _SalesSig()

    def _on_sales_refreshed(changed: bool):
        view = window.view("deals")
        if changed and view is not None and hasattr(view, "refresh"):
            try:
                view.refresh(force=True)
            except TypeError:
                view.refresh()
    sales_sig.done.connect(_on_sales_refreshed)

    from services.sale_images import refresh_all as _refresh_sales
    _refresh_sales(on_done=sales_sig.done.emit)

    app.aboutToQuit.connect(_auto_sync_drive_exit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()