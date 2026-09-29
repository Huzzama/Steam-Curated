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


def _self_test() -> int:
    """`--self-test`: check the bundled resources and build the whole UI
    offscreen. The release pipeline runs it on every packaged build."""
    import os
    from config import APP_VERSION, BUNDLE_DIR
    problems = []
    for rel in ("locales/en.json", "locales/es.json", "assets/fonts/Inter-Regular.ttf",
                "assets/fonts/SpaceMono-Bold.ttf", "assets/fonts/BebasNeue-Regular.ttf", "VERSION"):
        if not (BUNDLE_DIR / rel).exists():
            problems.append(f"missing resource: {BUNDLE_DIR / rel}")
    if APP_VERSION == "0.0.0":
        problems.append("VERSION not readable")
    from PySide6.QtWidgets import QApplication
    from ui import theme
    from ui.app_window import AppWindow
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    window = AppWindow()
    window.show()
    app.processEvents()
    for key in ("wishlist", "deals", "settings"):
        try:
            window.show_view(key)
            app.processEvents()
        except Exception as e:  # noqa: BLE001
            problems.append(f"view {key}: {type(e).__name__}: {e}")
    window.close()
    msg = ("SELF-TEST FAILED\n  " + "\n  ".join(problems)) if problems \
        else f"SELF-TEST OK — Steam Curator {APP_VERSION}"
    print(msg)
    # Windowed builds (Windows .exe, macOS .app) have no console: CI reads this file.
    if os.environ.get("CURATOR_SELFTEST_LOG"):
        with open(os.environ["CURATOR_SELFTEST_LOG"], "w", encoding="utf-8") as f:
            f.write(msg + "\n")
    return 1 if problems else 0


def main():
    if "--version" in sys.argv:
        from config import APP_VERSION
        print(APP_VERSION)
        return
    settings = load_settings()
    i18n.load_locale(settings.get("locale", "es"))
    if "--self-test" in sys.argv:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.exit(_self_test())
    _setup_logging()

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

    # Older versions stored absolute lows from a third-party API (often in USD);
    # re-derive every low from the deal history in the game's own currency.
    try:
        from services import price_history
        n = price_history.recompute_all()
        if n:
            log.info("re-derived %d all-time lows in local currency", n)
    except Exception as e:  # noqa: BLE001
        log.warning("low recompute skipped: %s", e)

    window = AppWindow()
    window.show()
    # Daily price check → every sale lands in the deal history (services.price_watch)
    window.start_price_watch()
    # Purchases not yet on pimpmysteam.com → sent and verified against the Steam library
    window.start_purchase_sync()
    # Discord alerts: re-upload the watchlist if it changed while the app was closed
    window.schedule_alert_sync(15000)
    # New release on GitHub? (once a day, never blocks, toast + Settings › About)
    window.start_update_check()

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