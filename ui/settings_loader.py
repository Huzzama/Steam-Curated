"""
settings.json — the only reader/writer. Cached in memory and re-read only
when the file's mtime changes (views used to hit the disk on every call,
once per card while rendering).
"""
import json
import os
import threading
from typing import Any

_DEFAULTS = {
    "locale":          "es",
    "country":         "mx",
    "timezone":        "GMT-6",
    "steamgriddb_key": "",
    "itad_key":        "",
    "compare_regions": [],
}

_lock  = threading.Lock()
_cache: dict | None = None
_mtime: float = -1.0


def _get_path():
    from config import BASE_DIR
    return BASE_DIR / "settings.json"


def load_settings() -> dict:
    global _cache, _mtime
    path = _get_path()
    with _lock:
        try:
            mtime = path.stat().st_mtime if path.exists() else 0.0
        except OSError:
            mtime = 0.0
        if _cache is not None and mtime == _mtime:
            return dict(_cache)
        data: dict = {}
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
            except Exception:  # noqa: BLE001
                data = {}
        _cache = {**_DEFAULTS, **data}
        _mtime = mtime
        return dict(_cache)


def save_settings(data: dict) -> None:
    """Merge *data* into settings.json (atomic write)."""
    global _cache, _mtime
    path = _get_path()
    with _lock:
        current = dict(_cache) if _cache is not None else {}
        merged = {**_DEFAULTS, **current, **data}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        _cache = merged
        try:
            _mtime = path.stat().st_mtime
        except OSError:
            _mtime = -1.0


def get_settings() -> dict:
    return load_settings()


def get(key: str, default: Any = None) -> Any:
    return load_settings().get(key, default)
