import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import i18n
from ui.settings_loader import load_settings


def _auto_sync_drive_startup():
    try:
        from services.drive_sync import is_configured, is_authenticated, download_all
        if is_configured() and is_authenticated():
            import threading
            def _dl():
                result = download_all()
                if result["downloaded"] > 0:
                    print(f"[Drive] Auto-synced {result['downloaded']} files on startup")
            threading.Thread(target=_dl, daemon=True).start()
    except Exception as e:
        print(f"[Drive] Auto-sync skipped: {e}")


def _auto_sync_drive_exit():
    try:
        from services.drive_sync import is_configured, is_authenticated, upload_all
        if is_configured() and is_authenticated():
            print("[Drive] Uploading on exit...")
            upload_all()
    except Exception as e:
        print(f"[Drive] Exit sync skipped: {e}")


def main():
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
    from PySide6.QtGui import QFontDatabase
    from ui.app_window import AppWindow

    # ── macOS: AA_DontUseNativeMenuBar keeps the sidebar nav reliable ─────────
    if sys.platform == "darwin":
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Register Space Mono if bundled, suppress warning if not available
    from pathlib import Path as _P
    _font_dir = _P(__file__).parent / "assets" / "fonts" / "SpaceMono"
    for _ext in ("*.ttf", "*.otf"):
        for _f in _font_dir.glob(_ext) if _font_dir.exists() else []:
            QFontDatabase.addApplicationFont(str(_f))

    # Dark palette
    from PySide6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(9,9,11))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(244,244,245))
    palette.setColor(QPalette.ColorRole.Base,            QColor(20,20,24))
    palette.setColor(QPalette.ColorRole.Text,            QColor(244,244,245))
    palette.setColor(QPalette.ColorRole.Button,          QColor(20,20,24))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(244,244,245))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(96,165,250))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0,0,0))
    app.setPalette(palette)

    app.setStyleSheet("""
        QLabel      { background-color: transparent; border: none; }
        QFrame      { border: none; }
        QScrollArea { border: none; }
        QWidget     { background-color: transparent; }
        QMainWindow > QWidget { background-color: #09090b; }
        QToolTip    { background-color: #141418; color: #f4f4f5; border: 1px solid #27272a; }
    """)

    window = AppWindow()
    window.show()

    # macOS: explicitly activate the app so all views get proper focus/paint events.
    # Without this, views opened after launch (Deals, Dashboard, etc.) can appear
    # blank because macOS never delivered the initial expose event to them.
    if sys.platform == "darwin":
        app.setActiveWindow(window)

    # Refresh sale images AFTER Qt is running — re-renders DealsView when done
    def _on_images_ready():
        from PySide6.QtCore import QTimer
        view = window._views.get("deals")
        if view and hasattr(view, "refresh"):
            QTimer.singleShot(0, view.refresh)

    from services.sale_images import refresh_all as _refresh_sales
    _refresh_sales(on_done=_on_images_ready)

    app.aboutToQuit.connect(_auto_sync_drive_exit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()