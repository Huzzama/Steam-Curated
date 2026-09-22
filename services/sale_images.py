"""
Sale banners + sale dates from the PimpMySteam server.

Strategy: keep a persistent cache on disk and refresh it in the background.
On startup the Deals screen renders immediately from the cached banners and
cached sales_dates.json; when the refresh finishes the view is told to
re-render (via a Qt-safe callback supplied by the caller).

The previous version deleted the cache on every launch and re-downloaded
everything, so the screen stayed blank (and polled for 20 s per banner)
whenever the backend was slow or offline.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from config import BASE_DIR
from services._http import SESSION

log = logging.getLogger("curator.sales")

_sale_events: list[dict] = []
_images: dict[str, Path] = {}          # key → local path
_ready = False
_lock  = threading.Lock()


def _api_url() -> str:
    from services.steamkustom_auth import get_api_url
    return get_api_url()


def _cache_dir() -> Path:
    d = BASE_DIR / "sale_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _events_file() -> Path:
    return _cache_dir() / "sales_dates.json"


def _load_from_disk() -> None:
    """Populate the in-memory registry from what a previous run cached."""
    global _sale_events
    cache = _cache_dir()
    with _lock:
        for f in cache.iterdir():
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                _images[f.stem] = f
        try:
            payload = json.loads(_events_file().read_text(encoding="utf-8"))
            _sale_events = payload.get("events", []) or []
        except Exception:  # noqa: BLE001
            _sale_events = []


def get_local_path(key: str) -> Optional[Path]:
    with _lock:
        return _images.get(key)


def get_sale_events() -> list[dict]:
    """Events from the server JSON (last cached copy if offline). [] → caller
    falls back to config.STEAM_SALE_EVENTS."""
    with _lock:
        return list(_sale_events)


def is_ready() -> bool:
    with _lock:
        return _ready


def _download_all() -> bool:
    """Refresh banners + dates. Returns True if anything changed."""
    global _sale_events
    changed = False
    cache = _cache_dir()
    api = _api_url()

    # 1. Sale dates
    try:
        r = SESSION.get(f"{api}/static/sale-images/sales_dates.json", timeout=15)
        r.raise_for_status()
        payload = r.json()
        events = payload.get("events", []) or []
        if events:
            with _lock:
                if events != _sale_events:
                    _sale_events = events
                    changed = True
            _events_file().write_text(json.dumps(payload), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.info("sales_dates.json not refreshed: %s", e)

    # 2. Banner images
    try:
        r = SESSION.get(f"{api}/stats/sale-images", timeout=15)
        r.raise_for_status()
        images = r.json().get("images", {}) or {}
    except Exception as e:  # noqa: BLE001
        log.info("sale-images list not refreshed: %s", e)
        images = {}

    for key, path in images.items():
        url = path if path.startswith("http") else f"{api}{path}"
        ext = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ".jpg"
        dest = cache / f"{key}{ext}"
        try:
            headers = {}
            if dest.exists():
                # Ask the server only for a newer copy
                from email.utils import formatdate
                headers["If-Modified-Since"] = formatdate(dest.stat().st_mtime, usegmt=True)
            r = SESSION.get(url, headers=headers, timeout=20)
            if r.status_code == 304:
                continue
            r.raise_for_status()
            dest.write_bytes(r.content)
            with _lock:
                _images[key] = dest
            changed = True
        except Exception as e:  # noqa: BLE001
            log.info("banner %s not refreshed: %s", key, e)
            if dest.exists():
                with _lock:
                    _images[key] = dest
    return changed


def refresh_all(on_done: Optional[Callable[[bool], None]] = None) -> None:
    """
    Load the cached copy now, refresh from the server in a thread, then call
    on_done(changed) FROM THE WORKER THREAD — callers must hop back to the
    GUI thread themselves (see ui.async_bridge.run_async).
    """
    global _ready
    _load_from_disk()

    def _work():
        global _ready
        try:
            changed = _download_all()
        except Exception as e:  # noqa: BLE001
            log.warning("sale refresh failed: %s", e)
            changed = False
        with _lock:
            _ready = True
        if on_done:
            on_done(changed)

    threading.Thread(target=_work, daemon=True).start()
