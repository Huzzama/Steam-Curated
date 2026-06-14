import time
from typing import Optional

import requests
import certifi

_SESSION = requests.Session()
_SESSION.headers.update({"Accept-Language": "en-US,en;q=0.9"})
_SESSION.verify = certifi.where()

_cache: dict   = {}
_CACHE_TTL     = 1800   # 30 min


def _cached(key: str, fn):
    entry = _cache.get(key)
    if entry and (time.time() - entry[1]) < _CACHE_TTL:
        return entry[0]
    result = fn()
    if result is not None:
        _cache[key] = (result, time.time())
    return result


def _get_credentials() -> tuple[Optional[str], Optional[str]]:
    """
    Return (steam_id64, api_key).
    steam_id64  → settings.json["steam_id64"]
    api_key     → PimpMySteam backend /auth/steam-api-key via JWT
    """
    try:
        from ui.settings_loader import get_settings
        s        = get_settings()
        steam_id = s.get("steam_id64", "").strip() or None
        if not steam_id:
            return None, None

        from services.steamkustom_auth import get_steam_api_key
        api_key = get_steam_api_key()
        return steam_id, api_key
    except Exception as e:
        print(f"[LibraryAPI] credentials error: {e}")
        return None, None


def get_owned_games(steam_id: str, api_key: str) -> list[dict]:
    """
    Fetch all owned games with playtime.
    Each item: {appid, name, playtime_forever (minutes), playtime_2weeks?}
    """
    def _fetch():
        try:
            r = _SESSION.get(
                "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/",
                params={
                    "key":                       api_key,
                    "steamid":                   steam_id,
                    "include_appinfo":           1,
                    "include_played_free_games": 1,
                    "skip_unvetted_apps":        0,
                },
                timeout=15,
            )
            r.raise_for_status()
            return r.json().get("response", {}).get("games", [])
        except Exception as e:
            print(f"[LibraryAPI] GetOwnedGames error: {e}")
            return None

    return _cached(f"owned:{steam_id}", _fetch) or []


def get_recently_played(steam_id: str, api_key: str, count: int = 10) -> list[dict]:
    """Fetch recently played games (last 2 weeks)."""
    def _fetch():
        try:
            r = _SESSION.get(
                "https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v1/",
                params={"key": api_key, "steamid": steam_id, "count": count},
                timeout=10,
            )
            r.raise_for_status()
            return r.json().get("response", {}).get("games", [])
        except Exception as e:
            print(f"[LibraryAPI] GetRecentlyPlayed error: {e}")
            return None

    return _cached(f"recent:{steam_id}", _fetch) or []


def get_library_stats(steam_id: str = None, api_key: str = None) -> Optional[dict]:
    """
    Compute all library stats. Returns None if credentials missing or API fails.

    Keys: total_games, total_playtime_hours, avg_playtime_hours,
          most_played, least_played, never_played_count, played_count,
          recently_played, top_played
    """
    if not steam_id or not api_key:
        steam_id, api_key = _get_credentials()
    if not steam_id or not api_key:
        print("[LibraryAPI] No credentials available")
        return None

    games = get_owned_games(steam_id, api_key)
    if not games:
        return None

    def mins_to_h(m: int) -> float:
        return round(m / 60, 1)

    total_mins   = sum(g.get("playtime_forever", 0) for g in games)
    played       = [g for g in games if g.get("playtime_forever", 0) > 0]
    never_played = [g for g in games if g.get("playtime_forever", 0) == 0]

    most_played  = max(played, key=lambda g: g.get("playtime_forever", 0)) if played else None
    least_played = min(played, key=lambda g: g.get("playtime_forever", 0)) if played else None

    recently = get_recently_played(steam_id, api_key)

    return {
        "total_games":          len(games),
        "total_playtime_hours": mins_to_h(total_mins),
        "avg_playtime_hours":   round(mins_to_h(total_mins) / len(played), 1) if played else 0,
        "never_played_count":   len(never_played),
        "played_count":         len(played),
        "most_played": {
            "name":  most_played.get("name", "?"),
            "hours": mins_to_h(most_played.get("playtime_forever", 0)),
            "appid": str(most_played.get("appid", "")),
        } if most_played else None,
        "least_played": {
            "name":  least_played.get("name", "?"),
            "hours": mins_to_h(least_played.get("playtime_forever", 0)),
            "appid": str(least_played.get("appid", "")),
        } if least_played else None,
        "recently_played": [
            {
                "name":        g.get("name", "?"),
                "appid":       str(g.get("appid", "")),
                "hours_2w":    mins_to_h(g.get("playtime_2weeks", 0)),
                "hours_total": mins_to_h(g.get("playtime_forever", 0)),
            }
            for g in recently[:8]
        ],
        "top_played": [
            {
                "name":  g.get("name", "?"),
                "appid": str(g.get("appid", "")),
                "hours": mins_to_h(g.get("playtime_forever", 0)),
            }
            for g in sorted(played,
                            key=lambda g: g.get("playtime_forever", 0),
                            reverse=True)[:10]
        ],
    }


def invalidate_cache():
    _cache.clear()