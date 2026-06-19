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


def bulk_refresh_prices(
    games: list,
    country: str = "mx",
    on_progress: callable = None,
    on_done: callable = None,
    max_workers: int = 6,
    force: bool = True,
):
    """
    Refresh the price of every game in `games` against the live Steam API,
    persisting any changes to the repository. Runs in a background thread —
    non-blocking.

    Without this, prices only ever update one game at a time when a user
    happens to open that game's detail panel (game_detail_panel.py's
    _refresh_prices) — sale prices for everything else go stale until
    manually visited.

    IMPORTANT — write strategy: the network calls run in parallel across
    `max_workers` threads (that part benefits from concurrency — it's I/O
    bound and Steam is the bottleneck), but NONE of those worker threads
    touch the repository directly. Each worker only computes the new
    price in memory. After every worker finishes, a single
    repo.update_many() call writes everything to disk in one pass.

    This used to call repo.update(game) from inside each worker thread —
    that meant up to `max_workers` threads were each doing a full
    read-modify-write of the entire wishlist.json concurrently, with no
    lock. Two problems resulted: (1) it was a lost-update race — a later
    thread's write could silently clobber an earlier thread's, so some
    "updated" games never actually got their new price saved; and (2) up
    to 60+ full-file disk writes serialized through Python's GIL kept the
    main/UI thread starved long enough that the progress bar's
    QTimer.singleShot(0, ...) callbacks all queued up and only flushed
    at the very end — which looked exactly like "stuck at 0/N, then
    jumps to done."

    Args:
        games:       list of Game objects (from repo.get_all())
        country:     Steam store country code for pricing
        on_progress: callback(current: int, total: int, game_name: str)
        on_done:     callback(updated: int, unchanged: int, failed: int)
        max_workers: parallel request threads (default 6)
        force:       bypass the 1h price cache so every call hits Steam
                     fresh (default True — a manual/sync-triggered refresh
                     should never return stale cached data)
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import data.repository as repo

    total = len(games)
    if total == 0:
        if on_done:
            on_done(0, 0, 0)
        return

    counter      = [0]   # processed
    unchanged_c  = [0]
    failed_c     = [0]
    to_save      = []    # games whose price actually changed — written once at the end
    lock         = threading.Lock()

    def _refresh_one(game):
        """Network-only — never touches the repository."""
        result = "failed"
        try:
            if force:
                _app_details_cache.pop(f"{game.app_id}:{country}", None)
                _price_cache.pop(f"{game.app_id}:{country}", None)
            data = get_app_details(game.app_id, country=country)
            new_price = parse_price(data) if data else None

            if new_price is not None:
                old_price = game.price
                changed = (
                    old_price is None
                    or old_price.current != new_price.current
                    or old_price.is_on_sale != new_price.is_on_sale
                )
                game.price = new_price
                result = "updated" if changed else "unchanged"
            else:
                result = "failed"
        except Exception:
            result = "failed"

        with lock:
            counter[0] += 1
            if result == "updated":
                to_save.append(game)
            elif result == "unchanged":
                unchanged_c[0] += 1
            else:
                failed_c[0] += 1
            current = counter[0]

        if on_progress:
            try:
                on_progress(current, total, game.name)
            except Exception:
                pass

    def _run():
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_refresh_one, g): g for g in games}
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    with lock:
                        failed_c[0] += 1

        # Single write pass for every game whose price actually changed —
        # see the docstring above for why this replaced per-game writes.
        updated_count = 0
        if to_save:
            try:
                updated_count = repo.update_many(to_save)
            except Exception as e:
                print(f"[SteamAPI] bulk_refresh_prices: update_many failed: {e}")
                with lock:
                    failed_c[0] += len(to_save)
                updated_count = 0

        if on_done:
            try:
                on_done(updated_count, unchanged_c[0], failed_c[0])
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()


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