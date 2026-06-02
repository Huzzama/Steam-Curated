"""
SteamKustom authentication for Steam Curator desktop app.

The user logs in at steamkustom.com, generates a token from
Settings → Apps → Generate Token, and pastes it here.

This token gives the app access to:
  - Google Drive sync (via /google/drive-token)
  - Steam wishlist import (via /steam/wishlist/{steam_id})
  - User profile data (via /auth/me)
"""
import json
import requests
from pathlib import Path
from typing import Optional
from config import BASE_DIR

SETTINGS_PATH = BASE_DIR / "settings.json"
API_URL       = "https://steamkustom-production.up.railway.app"


def get_token() -> Optional[str]:
    try:
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f).get("steamkustom_token", "")
    except Exception:
        pass
    return None


def save_token(token: str) -> bool:
    try:
        data = {}
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        data["steamkustom_token"] = token
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def verify_token(token: str) -> Optional[dict]:
    """Returns user dict if token is valid, None otherwise."""
    try:
        resp = requests.get(
            f"{API_URL}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def get_user() -> Optional[dict]:
    """Get current user from saved token."""
    token = get_token()
    if not token:
        return None
    return verify_token(token)


def get_drive_token() -> Optional[str]:
    """Get Google Drive access token from API."""
    token = get_token()
    if not token:
        return None
    try:
        resp = requests.get(
            f"{API_URL}/google/drive-token",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:
        pass
    return None


def get_steam_id() -> Optional[str]:
    """Get linked Steam ID from user profile."""
    user = get_user()
    if user:
        return user.get("steam_id") or user.get("steam_id64")
    return None


def is_connected() -> bool:
    return bool(get_token()) and bool(get_user())
