"""
Steam library stats (owned games, playtime) from pimpmysteam.com
(/steam/me/games, the key stays on the server) or, as a fallback, the public
community profile XML — the app never holds a Web API key. The SteamID64 comes from the linked
PimpMySteam account (creds.json). Errors are raised as LibraryError with
a user-readable message — the view shows it instead of an empty tab.
"""
import logging
import re
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
    Owned games with playtime. First from pimpmysteam.com (GET /steam/me/games —
    the Steam Web API through the server's key), falling back to the public
    community profile XML (steamcommunity.com/profiles/<id>/games?xml=1) when
    the backend doesn't have that endpoint yet or can't be reached.
    Each item: {appid, name, playtime_forever (min), playtime_2weeks (min)}
    """
    def _from_backend() -> Optional[list[dict]]:
        from services._http import ApiError, Unreachable
        from services.steamkustom_auth import api, get_token
        if not get_token():
            return None
        try:
            data = api("/steam/me/games", timeout=30)
        except (ApiError, Unreachable) as e:
            log.info("library via backend unavailable (%s) — using the community XML", e)
            return None
        if data.get("private"):
            raise LibraryError("Steam keeps your game list private — set “Game details” to Public "
                               "in your Steam privacy settings.")
        return [{"appid": str(g.get("appid", "")), "name": g.get("name") or "?",
                 "playtime_forever": int(g.get("playtime_forever") or 0),
                 "playtime_2weeks": int(g.get("playtime_2weeks") or 0)}
                for g in data.get("games") or []]

    def _fetch():
        try:
            r = _SESSION.get(f"https://steamcommunity.com/profiles/{steam_id}/games",
                             params={"tab": "all", "xml": "1"}, timeout=20)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            raise LibraryError(f"Steam community did not answer: {e}") from e
        return parse_games_xml(r.content)

    def _fetch_any():
        games = _from_backend()
        return games if games is not None else _fetch()
    return _cached(f"owned:{steam_id}", _fetch_any)


# XML 1.0 forbids most control characters even inside CDATA; Steam copies game
# names verbatim, so one odd name used to break the whole library
# ("not well-formed (invalid token): line 57, column 44").
_BAD_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_GAME_RE = re.compile(r"<game>(.*?)</game>", re.S)


def _tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</{name}>", block, re.S)
    return m.group(1).strip() if m else ""


def parse_games_xml(content: bytes) -> list[dict]:
    """Community games XML → [{appid, name, playtime_forever, playtime_2weeks}].
    Tolerates invalid characters/bytes in game names; a web page instead of XML
    (private profile, login wall, Steam hiccup) becomes a readable LibraryError."""
    import xml.etree.ElementTree as ET
    text = _BAD_XML_CHARS.sub("", content.decode("utf-8", errors="replace"))
    head = text.lstrip()[:200].lower()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        raise LibraryError("Steam answered with a web page instead of your game list — make sure "
                           "your profile and “Game details” are Public in Steam's privacy settings.")

    def row(appid, name, total, two_weeks):
        return {"appid": appid or "", "name": name or "?",
                "playtime_forever": _hours(total), "playtime_2weeks": _hours(two_weeks)}

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        # still malformed: pull the <game> blocks out one by one
        games = [row(_tag(b, "appID"), _tag(b, "name"), _tag(b, "hoursOnRecord"), _tag(b, "hoursLast2Weeks"))
                 for b in _GAME_RE.findall(text)]
        if games:
            log.warning("library XML malformed (%s) — parsed %d games leniently", e, len(games))
            return games
        err = _tag(text, "error")
        raise LibraryError(err or f"Steam sent an unreadable game list: {e}") from e
    err = root.findtext("error")
    if err:
        raise LibraryError(err.strip())
    return [row(g.findtext("appID", ""), g.findtext("name", ""), g.findtext("hoursOnRecord"),
                g.findtext("hoursLast2Weeks")) for g in root.iter("game")]


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