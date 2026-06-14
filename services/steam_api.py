"""
Steam API service — optimized with:
- LRU cache for app details (avoid redundant HTTP calls)
- Set-based lookups for O(1) membership checks
- Generator expressions instead of list comprehensions where possible
- lru_cache for pure functions
"""
import time as _time
from functools import lru_cache
from typing import Optional

import requests
from data.models import PriceInfo

# ── Price cache (1 hour TTL) ──────────────────────────────────────────────────
_price_cache: dict = {}
_PRICE_TTL = 3600

def _get_cached_price(app_id: str) -> Optional[PriceInfo]:
    entry = _price_cache.get(str(app_id))
    if entry and (_time.time() - entry[1]) < _PRICE_TTL:
        return entry[0]
    return None

def _set_cached_price(app_id: str, price: PriceInfo):
    _price_cache[str(app_id)] = (price, _time.time())

def clear_price_cache():
    _price_cache.clear()

# ── HTTP session (reuse TCP connections) ──────────────────────────────────────
import certifi as _certifi
_SESSION = requests.Session()
_SESSION.headers.update({"Accept-Language": "en-US,en;q=0.9"})
_SESSION.verify = _certifi.where()  # fix SSL on macOS

# ── App details cache (immutable data — cache forever per session) ────────────
# Manual app details cache — only caches successes, never None
_app_details_cache: dict = {}

def _cached_app_details(app_id: str, country: str) -> Optional[dict]:
    """Cache app details — only caches successful responses."""
    key = f"{app_id}:{country}"
    if key in _app_details_cache:
        return _app_details_cache[key]
    url = "https://store.steampowered.com/api/appdetails"
    try:
        r = _SESSION.get(url, params={"appids": app_id, "cc": country,
                                       "l": "english"},
                         timeout=10)
        r.raise_for_status()
        data = r.json().get(str(app_id), {})
        if data.get("success") and data.get("data"):
            _app_details_cache[key] = data  # only cache success
            return data
        return None
    except Exception as _e:
        print(f"[SteamAPI] _cached_app_details({app_id}, {country}) error: {_e}")
        return None  # don't cache failures


def get_app_details(app_id: str, country: str = "mx") -> Optional[dict]:
    data = _cached_app_details(str(app_id), str(country).lower())
    return data.get("data") if data else None


def parse_price(data: dict) -> Optional[PriceInfo]:
    if not data:
        return None
    pd = data.get("price_overview")
    if not pd:
        return None
    return PriceInfo(
        current      = pd.get("final",    0) / 100,
        base         = pd.get("initial",  0) / 100,
        currency     = pd.get("currency", "USD"),
        discount_pct = pd.get("discount_percent", 0),
        is_on_sale   = pd.get("discount_percent", 0) > 0,
    )


def refresh_price(app_id: str, country: str = "mx") -> Optional[PriceInfo]:
    """Price refresh with 1h TTL cache per (app_id, country)."""
    cache_key = f"{app_id}:{country}"
    entry = _price_cache.get(cache_key)
    if entry and (_time.time() - entry[1]) < _PRICE_TTL:
        return entry[0]
    data  = get_app_details(app_id, country)
    price = parse_price(data) if data else None
    if price:
        _price_cache[cache_key] = (price, _time.time())
    return price


@lru_cache(maxsize=128)
def _parse_year_cached(date_str: str) -> int:
    """Cache year parsing — same string always returns same result."""
    import re
    m = re.search(r"\b(19|20)\d{2}\b", date_str)
    return int(m.group()) if m else 0


def get_game_metadata(app_id: str, country: str = "mx") -> Optional[dict]:
    """Full metadata for a game — name, genre, developer, description."""
    data = get_app_details(app_id, country)
    if not data:
        return None

    genres = data.get("genres", [])
    cats   = data.get("categories", [])

    return {
        "name":              data.get("name", ""),
        "short_description": data.get("short_description", ""),
        "developer":         ", ".join(data.get("developers", [])),
        "publisher":         ", ".join(data.get("publishers", [])),
        # Use join instead of string concat in loops
        "genre":             ", ".join(g["description"] for g in genres),
        "categories":        ", ".join(c["description"] for c in cats),
        "release_year":      _parse_year_cached(
                                 data.get("release_date", {}).get("date", "")),
        "price":             parse_price(data),
        "steam_url":         f"https://store.steampowered.com/app/{app_id}",
    }


def search_games(query: str, limit: int = 10, cc: str = "mx") -> list[dict]:
    """Search Steam store by name. Returns list of {app_id, name, icon}."""
    try:
        r = _SESSION.get(
            "https://store.steampowered.com/api/storesearch/",
            params={"term": query, "l": "english", "cc": cc},
            timeout=8,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        return [
            {
                "id":     str(item["id"]),
                "app_id": str(item["id"]),
                "name":   item.get("name", ""),
                "icon":   item.get("small_capsule_image", ""),
                "price":  item.get("price", {}).get("final", 0) / 100 if item.get("price") else 0,
            }
            for item in items[:limit]
        ]
    except Exception:
        return []


def parse_metadata(data: dict) -> dict:
    """
    Parse full app details dict into metadata dict.
    Alias for get_game_metadata internals — keeps backward compat.
    """
    if not data:
        return {}
    genres = data.get("genres", [])
    cats   = data.get("categories", [])
    return {
        "name":              data.get("name", ""),
        "short_description": data.get("short_description", ""),
        "developer":         ", ".join(data.get("developers", [])),
        "publisher":         ", ".join(data.get("publishers", [])),
        "genre":             ", ".join(g["description"] for g in genres),
        "categories":        ", ".join(c["description"] for c in cats),
        "release_year":      _parse_year_cached(
                                 data.get("release_date", {}).get("date", "")),
        "price":             parse_price(data),
        "steam_url":         f"https://store.steampowered.com/app/{data.get('steam_appid', '')}",
    }
