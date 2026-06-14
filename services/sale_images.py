"""
Sale image loader — downloads images from PimpMySteam server.

Strategy: always re-download on startup (delete old cache first).
This ensures server-side image updates are reflected immediately.
Images are stored in a session temp dir that's cleared each run.
"""
import threading
import urllib.request
import ssl
import json
from pathlib import Path
from typing import Optional, Callable

API_URL = "https://api.pimpmysteam.com"

# In-memory registry: key → local Path (populated after download)
_session_images: dict[str, Path] = {}
_download_done  = False
_done_callbacks: list[Callable] = []
_lock           = threading.Lock()

# Sale events loaded from server JSON (same session lifetime as images)
_sale_events: list[dict] = []

SALES_DATES_URL = f"{API_URL}/static/sale-images/sales_dates.json"


def _cache_dir() -> Path:
    import sys
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "SteamCurator"
    elif sys.platform == "win32":
        import os
        base = Path(os.environ.get("APPDATA", Path.home())) / "SteamCurator"
    else:
        base = Path.home() / ".local" / "share" / "SteamCurator"
    d = base / "sale_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clear_cache():
    """Delete all cached images — called once per session on startup."""
    try:
        cache = _cache_dir()
        for f in cache.iterdir():
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                f.unlink()
        print(f"[SaleImages] Cache cleared for fresh session")
    except Exception as e:
        print(f"[SaleImages] Cache clear error: {e}")


def get_local_path(key: str) -> Optional[Path]:
    """Return the local path for a given image key, or None if not downloaded yet."""
    with _lock:
        return _session_images.get(key)


def get_sale_events() -> list[dict]:
    """
    Return sale events loaded from the server JSON.
    Returns an empty list if the download hasn't completed or failed —
    callers should fall back to config.STEAM_SALE_EVENTS in that case.
    """
    with _lock:
        return list(_sale_events)


def _fetch(url: str, timeout: int = 15) -> Optional[bytes]:
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SteamCurator/2.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.read()
    except Exception as e:
        print(f"[SaleImages] fetch error {url[:80]}: {e}")
        return None


def _download_sale_dates():
    """
    Fetch sales_dates.json from the server and populate _sale_events.
    Called at the end of _download_all() so events and images share
    the same session lifecycle.
    """
    global _sale_events
    print("[SaleImages] Fetching sales_dates.json from server…")
    try:
        data = _fetch(SALES_DATES_URL)
        if not data:
            print("[SaleImages] No sales_dates.json from server — "
                  "falling back to config.STEAM_SALE_EVENTS")
            return
        payload = json.loads(data)
        events  = payload.get("events", [])
        if events:
            with _lock:
                _sale_events = events
            print(f"[SaleImages] Loaded {len(events)} sale events from server")
        else:
            print("[SaleImages] sales_dates.json contained no events — "
                  "falling back to config.STEAM_SALE_EVENTS")
    except Exception as e:
        print(f"[SaleImages] sales_dates.json fetch error: {e} — "
              "falling back to config.STEAM_SALE_EVENTS")


def _download_all():
    global _download_done
    print("[SaleImages] Fetching image list from server…")
    try:
        data = _fetch(f"{API_URL}/stats/sale-images")
        if not data:
            print("[SaleImages] No data from server")
            return
        images = json.loads(data).get("images", {})
        print(f"[SaleImages] Server has {len(images)} images: {list(images.keys())}")
        cache  = _cache_dir()

        for key, path in images.items():
            url = path if path.startswith("http") else f"{API_URL}{path}"
            ext = "." + path.split(".")[-1] if "." in path.split("/")[-1] else ".jpg"
            img_data = _fetch(url)
            if img_data:
                dest = cache / f"{key}{ext}"
                dest.write_bytes(img_data)
                with _lock:
                    _session_images[key] = dest
                print(f"[SaleImages] Downloaded: {key}")
            else:
                print(f"[SaleImages] Failed: {key}")
    except Exception as e:
        print(f"[SaleImages] download error: {e}")
    finally:
        with _lock:
            _download_done = True

    # ── Fetch sale event dates (runs after images, regardless of image errors) ─
    _download_sale_dates()


def refresh_all(on_done: Callable = None):
    """
    Clear cache and re-download all images from server.
    Calls on_done() in the download thread when complete.
    """
    global _download_done, _session_images, _sale_events
    with _lock:
        _download_done  = False
        _session_images = {}
        _sale_events    = []

    _clear_cache()

    def _work():
        _download_all()
        if on_done:
            on_done()

    threading.Thread(target=_work, daemon=True).start()


def is_ready() -> bool:
    with _lock:
        return _download_done


# Backward compat
def cache_dir():
    return _cache_dir()

def get_banner_path(event_key, **_):
    p = get_local_path(event_key)
    return str(p) if p else ""