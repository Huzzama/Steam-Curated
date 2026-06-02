import json
from pathlib import Path
from config import LOCALES_DIR, DEFAULT_LOCALE, LOCALES

_translations: dict = {}
_current_locale: str = DEFAULT_LOCALE


def load_locale(locale: str) -> None:
    global _translations, _current_locale
    path = LOCALES_DIR / f"{locale}.json"
    if not path.exists():
        path = LOCALES_DIR / f"{DEFAULT_LOCALE}.json"
    with open(path, encoding="utf-8") as f:
        _translations = json.load(f)
    _current_locale = locale


def t(key: str, **kwargs) -> str:
    """Translate a key, with optional format kwargs."""
    parts = key.split(".")
    val = _translations
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p, key)
        else:
            return key
    if isinstance(val, str) and kwargs:
        return val.format(**kwargs)
    return val if isinstance(val, str) else key


def current_locale() -> str:
    return _current_locale


def available_locales() -> dict:
    return LOCALES
