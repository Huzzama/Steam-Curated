"""
Steam library stats (owned games, playtime) from the public community
profile XML — no Web API key involved. The SteamID64 comes from the linked
PimpMySteam account (creds.json). Errors are raised as LibraryError with
a user-readable message — the view shows it instead of an empty tab.
"""
import logging
import time
from typing import Optional

from services._http import SESSION as _SESSION

log = logging.getLogger("curator.library")

_cache: dict   = {}
_CACHE_TTL     = 1800   # 30 min


class LibraryError(Exception):
    """User-facing reason why library stats are unavailable."""


def _cached(key: str, fn):
    entry = _cache.get(key)
    if entry and (time.time() - entry[1]) < _CACHE_TTL:
        return entry[0]
    result = fn()
    if result is not None:
        _cache[key] = (result, time.time())
    return result


def _get_steam_id() -> str:
    """SteamID64 of the linked account, or raise LibraryError explaining what is missing."""
    from services.steamkustom_auth import get_token, get_steam_id
    if not get_token():
        raise LibraryError("Connect your PimpMySteam account in Settings.")
    steam_id = get_steam_id()
    if not steam_id:
        raise LibraryError("No Steam account linked — link Steam on pimpmysteam.com › Settings, "
                           "then reconnect the app.")
    return steam_id


def _hours(text: Optional[str]) -> int:
    """'1,234.5' (hours, community XML) → minutes."""
    if not text:
        return 0
    try:
        return int(round(float(text.replace(",", "")) * 60))
    except ValueError:
        return 0


def get_owned_games(steam_id: str, api_key: str = None) -> list[dict]:
    """
    Owned games with playtime from the public community profile
    (steamcommunity.com/profiles/<id>/games?xml=1 — no API key needed, but the
    profile's "Game details" must be public).
    Each item: {appid, name, playtime_forever (min), playtime_2weeks (min)}
    """
    def _fetch():
        import xml.etree.ElementTree as ET
        try:
            r = _SESSION.get(f"https://steamcommunity.com/profiles/{steam_id}/games",
                             params={"tab": "all", "xml": "1"}, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:  # noqa: BLE001
            raise LibraryError(f"Steam community did not answer: {e}") from e
        err = root.findtext("error")
        if err:
            raise LibraryError(err.strip())
        games = []
        for g in root.iter("game"):
            games.append({
                "appid":            g.findtext("appID", ""),
                "name":             g.findtext("name", "") or "?",
                "playtime_forever": _hours(g.findtext("hoursOnRecord")),
                "playtime_2weeks":  _hours(g.findtext("hoursLast2Weeks")),
            })
        return games
    return _cached(f"owned:{steam_id}", _fetch)


def get_recently_played(steam_id: str, api_key: str = None, count: int = 10) -> list[dict]:
    """Games with playtime in the last two weeks, most played first."""
    games = [g for g in get_owned_games(steam_id) if g.get("playtime_2weeks", 0) > 0]
    games.sort(key=lambda g: g["playtime_2weeks"], reverse=True)
    return games[:count]


def get_library_stats(steam_id: str = None, api_key: str = None) -> Optional[dict]:
    """
    Compute all library stats. Raises LibraryError with a user-facing reason.

    Keys: total_games, total_playtime_hours, avg_playtime_hours,
          most_played, least_played, never_played_count, played_count,
          recently_played, top_played
    """
    if not steam_id:
        steam_id = _get_steam_id()

    games = get_owned_games(steam_id)
    if not games:
        raise LibraryError("Steam returned no games — set “Game details” to Public in your "
                           "Steam privacy settings.")

    def mins_to_h(m: int) -> float:
        return round(m / 60, 1)

    total_mins   = sum(g.get("playtime_forever", 0) for g in games)
    played       = [g for g in games if g.get("playtime_forever", 0) > 0]
    never_played = [g for g in games if g.get("playtime_forever", 0) == 0]

    most_played  = max(played, key=lambda g: g.get("playtime_forever", 0)) if played else None
    least_played = min(played, key=lambda g: g.get("playtime_forever", 0)) if played else None

    recently = get_recently_played(steam_id)

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