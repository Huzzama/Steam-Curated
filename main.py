import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import i18n
from ui.history_settings_views import load_settings


def _auto_sync_on_startup():
    """
    If the user is authenticated with Google Drive,
    silently download latest data in the background.
    """
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


def _auto_sync_on_exit(app):
    """Upload data when the app closes."""
    try:
        from services.drive_sync import is_configured, is_authenticated, upload_all
        if is_configured() and is_authenticated():
            print("[Drive] Uploading on exit...")
            upload_all()
    except Exception as e:
        print(f"[Drive] Exit sync skipped: {e}")
    finally:
        app.destroy()


def main():
    settings = load_settings()
    i18n.load_locale(settings.get("locale", "es"))

    # Auto-download on startup (background)
    _auto_sync_on_startup()

    from ui.app_window import AppWindow
    app = AppWindow()

    # Auto-upload on close
    app.protocol("WM_DELETE_WINDOW", lambda: _auto_sync_on_exit(app))

    app.mainloop()


if __name__ == "__main__":
    main()