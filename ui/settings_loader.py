"""Settings loader — thin wrapper used across the app."""
import json
from typing import Any


def _get_path():
    from config import BASE_DIR
    return BASE_DIR / "settings.json"


_DEFAULTS = {
    "locale":            "es",
    "country":           "mx",
    "steam_id64":        "",
    "steamgriddb_key":   "",
    "steamkustom_token": "",
    "wishlist_last_refresh": 0,
}


def load_settings() -> dict:
    path = _get_path()
    if not path.exists():
        return dict(_DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {**_DEFAULTS, **data}
    except Exception:
        return dict(_DEFAULTS)


def save_settings(data: dict) -> None:
    path = _get_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_settings() -> dict:
    return load_settings()