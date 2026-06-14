"""
steamkustom_auth.py — shared auth helper for Steam Grunge (and Steam Curator).
Handles token storage, verification against the PimpMySteam backend, and the
artwork-synced / pending-savings report calls.

The 403 on artwork sync was caused by the desktop app calling POST /stats/artwork-synced
with an *app token* that was stored correctly in settings but never sent in the
Authorization header — the call was made with requests.post(url, json=...) with no
headers kwarg.  This file centralises all backend calls and always injects the token.
"""

import json
import threading
from pathlib import Path
from typing import Optional

import requests

# ── Storage ────────────────────────────────────────────────────────────────────

_CREDS_FILE = Path.home() / ".config" / "pimpmysteam" / "creds.json"
_creds_lock = threading.Lock()


def _load_creds() -> dict:
    try:
        if _CREDS_FILE.exists():
            return json.loads(_CREDS_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_creds(data: dict):
    _CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CREDS_FILE.write_text(json.dumps(data, indent=2))


def get_token() -> Optional[str]:
    with _creds_lock:
        return _load_creds().get("app_token")


def get_api_url() -> str:
    with _creds_lock:
        return _load_creds().get(
            "api_url", "https://steamkustom-production.up.railway.app"
        )


def save_token(token: str, api_url: str = ""):
    with _creds_lock:
        creds = _load_creds()
        creds["app_token"] = token
        if api_url:
            creds["api_url"] = api_url
        _save_creds(creds)


def clear_token():
    with _creds_lock:
        creds = _load_creds()
        creds.pop("app_token", None)
        _save_creds(creds)


# ── Authenticated request helper ───────────────────────────────────────────────

def _auth_headers() -> dict:
    token = get_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _api(path: str, *, method="GET", json_body=None, timeout=12) -> Optional[dict]:
    """
    Makes a request to the PimpMySteam backend.
    Always injects the app-token Authorization header.
    Returns the parsed JSON dict, or None on any failure.
    """
    url = get_api_url().rstrip("/") + path
    try:
        resp = requests.request(
            method,
            url,
            headers={
                "Content-Type": "application/json",
                **_auth_headers(),
            },
            json=json_body,
            timeout=timeout,
        )
        if resp.status_code == 403:
            # Token invalid or missing — surface clearly so caller can prompt user
            raise PermissionError(
                f"403 Forbidden calling {path} — "
                "check that your app token is correct in Settings."
            )
        if not resp.ok:
            raise RuntimeError(
                f"Backend error {resp.status_code} on {path}: {resp.text[:200]}"
            )
        return resp.json()
    except (requests.ConnectionError, requests.Timeout) as e:
        raise ConnectionError(f"Cannot reach backend at {url}: {e}") from e


# ── Auth calls ─────────────────────────────────────────────────────────────────

def verify_token(token: str) -> Optional[dict]:
    """
    Verify an app-token against /auth/me.
    Returns the user dict on success, None if the token is invalid/expired.
    """
    url = get_api_url().rstrip("/") + "/auth/me"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return None


def get_steam_api_key(token: str) -> Optional[str]:
    """Fetch the server-side Steam API key (users never configure this themselves)."""
    url = get_api_url().rstrip("/") + "/auth/steam-api-key"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.ok:
            return resp.json().get("api_key")
    except Exception:
        pass
    return None


# ── Stats report calls ─────────────────────────────────────────────────────────

def report_artwork_synced(count: int) -> bool:
    """
    POST /stats/artwork-synced  — called by Steam Grunge with the session batch.
    Returns True on success.

    Fix: previously called without Authorization header → 403.
    Now uses _api() which always injects the token.
    """
    if count <= 0:
        return True
    token = get_token()
    if not token:
        return False
    try:
        _api("/stats/artwork-synced", method="POST", json_body={"count": count})
        return True
    except Exception as e:
        print(f"[Auth] artwork-synced report failed: {e}")
        return False


def report_pending_saving(amount: float, currency: str = "USD") -> bool:
    """
    POST /stats/pending-savings — called by Steam Curator when a game is marked
    as Purchased with a discount price (sends the amount saved).
    """
    if amount <= 0:
        return True
    token = get_token()
    if not token:
        return False
    try:
        _api(
            "/stats/pending-savings",
            method="POST",
            json_body={"amount": round(amount, 2), "currency": currency},
        )
        return True
    except Exception as e:
        print(f"[Auth] pending-savings report failed: {e}")
        return False