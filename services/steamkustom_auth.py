"""
PimpMySteam account — the one place the app token lives.

Token file: <BASE_DIR>/creds.json. Steam data (wishlist, profile) is proxied by
the backend under /steam/me/* — the app never holds a Steam Web API key.  (BASE_DIR follows the OS: %APPDATA%,
~/Library/Application Support, ~/.local/share). Older builds wrote it to
~/.config/pimpmysteam/creds.json and *also* to settings.json under
"steamkustom_token"; both are read once for migration and then ignored.

All backend calls go through api() so the token and the base URL are always
the same ones. Errors are typed: Unreachable (no network) vs ApiError
(server said no) — the UI can tell "check your connection" apart from
"invalid token".
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

import requests

from services._http import SESSION, ApiError, Unreachable

log = logging.getLogger("curator.auth")

DEFAULT_API_URL = "https://api.pimpmysteam.com"



def _creds_file() -> Path:
    import config
    return config.BASE_DIR / "creds.json"

_LEGACY_CREDS = Path.home() / ".config" / "pimpmysteam" / "creds.json"
_creds_lock   = threading.Lock()
_creds_cache: Optional[dict] = None


def _read_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as e:  # noqa: BLE001
        log.warning("could not read %s: %s", path, e)
    return {}


def _load_creds() -> dict:
    global _creds_cache
    if _creds_cache is not None:
        return _creds_cache
    creds = _read_json(_creds_file())
    if not creds.get("app_token"):
        # one-time migration from the two places older versions used
        legacy = _read_json(_LEGACY_CREDS)
        settings = _read_json(_creds_file().parent / "settings.json")
        token = legacy.get("app_token") or settings.get("steamkustom_token")
        if token:
            creds["app_token"] = token
            if legacy.get("api_url"):
                creds["api_url"] = legacy["api_url"]
            _write_creds(creds)
            log.info("migrated PimpMySteam token to %s", _creds_file())
    _creds_cache = creds
    return creds


def _write_creds(data: dict) -> None:
    global _creds_cache
    f = _creds_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, f)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    _creds_cache = data


def get_token() -> Optional[str]:
    with _creds_lock:
        return _load_creds().get("app_token") or None


def get_api_url() -> str:
    with _creds_lock:
        return (_load_creds().get("api_url") or DEFAULT_API_URL).rstrip("/")


def save_token(token: str, api_url: str = "") -> None:
    with _creds_lock:
        creds = dict(_load_creds())
        creds["app_token"] = token.strip()
        if api_url:
            creds["api_url"] = api_url.rstrip("/")
        _write_creds(creds)


def save_account(token: str, user: Optional[dict] = None) -> None:
    """Store the token plus what /auth/me told us (steam id, username)."""
    with _creds_lock:
        creds = dict(_load_creds())
        creds["app_token"] = token.strip()
        if user:
            sid = user.get("steam_id") or user.get("steam_id64") or ""
            if sid:
                creds["steam_id64"] = str(sid)
            if user.get("username"):
                creds["username"] = user["username"]
        _write_creds(creds)


def clear_token() -> None:
    with _creds_lock:
        creds = dict(_load_creds())
        for k in ("app_token", "steam_id64", "username"):
            creds.pop(k, None)
        _write_creds(creds)


def is_connected() -> bool:
    return bool(get_token())


def get_steam_id() -> Optional[str]:
    """SteamID64 of the linked account (filled in by verify → save_account)."""
    with _creds_lock:
        creds = _load_creds()
        sid = creds.get("steam_id64")
        if not sid:
            # legacy location
            sid = _read_json(_creds_file().parent / "settings.json").get("steam_id64")
        return str(sid) if sid else None


def get_username() -> str:
    with _creds_lock:
        return _load_creds().get("username", "") or ""


# ── Backend calls ──────────────────────────────────────────────────────────────

def api(path: str, *, method: str = "GET", json_body=None, token: Optional[str] = None,
        timeout: int = 12) -> dict:
    """
    Call the PimpMySteam backend with the app token.
    Raises Unreachable (network) or ApiError (status); returns parsed JSON.
    """
    token = token or get_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = get_api_url() + path
    try:
        resp = SESSION.request(method, url, headers=headers, json=json_body, timeout=timeout)
    except (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError) as e:
        raise Unreachable(str(e)) from e
    if not resp.ok:
        raise ApiError(resp.status_code, resp.text[:200])
    try:
        return resp.json()
    except ValueError:
        return {}


def verify_token(token: str) -> dict:
    """
    /auth/me with *token*. Returns the user dict.
    Raises ApiError(401/403) for a bad token, Unreachable for no network.
    """
    return api("/auth/me", token=token)


def get_steam_account(token: Optional[str] = None) -> dict:
    """GET /steam/me — which Steam account is linked to the PimpMySteam user.
    Raises ApiError / Unreachable."""
    data = api("/steam/me", token=token)
    return data if isinstance(data, dict) else {}


def _as_list(data) -> list:
    """Unwrap the shapes a Steam proxy can return into a plain list of items."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("items", "wishlist", "games", "players", "data", "results"):
        if isinstance(data.get(key), list):
            return data[key]
    resp = data.get("response")
    if isinstance(resp, dict):
        return _as_list(resp)
    if isinstance(resp, list):
        return resp
    # legacy wishlistdata shape: {"<appid>": {...}, ...}
    if data and all(str(k).isdigit() for k in data.keys()):
        return [dict(v, appid=k) for k, v in data.items() if isinstance(v, dict)]
    return []


def get_wishlist(token: Optional[str] = None) -> list[dict]:
    """
    GET /steam/me/wishlist (the Steam key stays on the server).
    Returns [{"appid": "1245620", "priority": 3, "date_added": 1700000000, "name": ""}, …]
    Raises ApiError (401 bad token, 404 no Steam account linked) / Unreachable.
    """
    items = _as_list(api("/steam/me/wishlist", token=token, timeout=30))
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        appid = it.get("appid") or it.get("app_id") or it.get("id")
        if appid is None:
            continue
        out.append({
            "appid":      str(appid),
            "priority":   int(it.get("priority") or 0),
            "date_added": int(it.get("date_added") or it.get("added") or 0),
            "name":       it.get("name") or "",
        })
    return out


def get_player_summary(token: Optional[str] = None) -> Optional[dict]:
    """GET /steam/me/summary → {name, avatar_url, profile_url, steam_id} or None."""
    try:
        data = api("/steam/me/summary", token=token)
    except (ApiError, Unreachable) as e:
        log.info("summary unavailable: %s", e)
        return None
    players = _as_list(data)
    p = players[0] if players else (data if isinstance(data, dict) else {})
    if not isinstance(p, dict) or not (p.get("personaname") or p.get("name")):
        return None
    return {
        "name":        p.get("personaname") or p.get("name") or "",
        "avatar_url":  p.get("avatarmedium") or p.get("avatarfull") or p.get("avatar") or p.get("avatar_url") or "",
        "profile_url": p.get("profileurl") or p.get("profile_url") or "",
        "steam_id":    str(p.get("steamid") or p.get("steam_id64") or p.get("steam_id") or ""),
    }


def report_pending_saving(amount: float, currency: str = "USD") -> bool:
    """POST /stats/pending-savings when a game is marked purchased at a discount."""
    if amount <= 0 or not get_token():
        return False
    try:
        api("/stats/pending-savings", method="POST",
            json_body={"amount": round(amount, 2), "currency": currency})
        return True
    except (ApiError, Unreachable) as e:
        log.warning("pending-savings report failed: %s", e)
        return False
