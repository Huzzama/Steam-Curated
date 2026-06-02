"""
Fetch and import a user's Steam wishlist via the Steam Web API.

Requires:
- SteamID64 (obtained via OpenID login)
- Steam Web API key (from steamcommunity.com/dev/apikey)
"""
import requests
from typing import Optional
from data.models import Game, PriceInfo
from datetime import datetime

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "SteamLibraryCurator/1.0"})


def fetch_wishlist(steam_id64: str, api_key: str, country: str = "mx") -> list[dict]:
    """
    Fetch the user's Steam wishlist.
    Returns a list of raw game dicts from the API.
    """
    url  = "https://api.steampowered.com/IWishlistService/GetWishlist/v1/"
    resp = _SESSION.get(url, params={
        "key":      api_key,
        "steamid":  steam_id64,
    }, timeout=15)
    resp.raise_for_status()
    data  = resp.json()
    items = data.get("response", {}).get("items", [])
    return items


def fetch_wishlist_with_details(
    steam_id64: str,
    api_key: str,
    country: str = "mx",
    on_progress: callable = None,
) -> list[dict]:
    """
    Fetch wishlist items and enrich each with store details.
    Returns list of dicts ready to convert to Game objects.
    """
    from services.steam_api import get_app_details, parse_metadata, parse_price

    raw_items = fetch_wishlist(steam_id64, api_key, country)
    total     = len(raw_items)
    enriched  = []

    for i, item in enumerate(raw_items):
        app_id = str(item.get("appid", ""))
        if not app_id:
            continue

        if on_progress:
            on_progress(i + 1, total, app_id)

        try:
            details = get_app_details(app_id, country=country)
            if not details:
                # Still add with minimal info
                enriched.append({
                    "app_id":   app_id,
                    "name":     f"App {app_id}",
                    "priority": item.get("priority", 0),
                })
                continue

            meta  = parse_metadata(details)
            price = parse_price(details)

            enriched.append({
                "app_id":      app_id,
                "name":        meta["name"],
                "genre":       meta["genre"],
                "release_year":meta["release_year"],
                "developer":   meta["developer"],
                "publisher":   meta["publisher"],
                "categories":  meta["categories"],
                "short_description": meta["short_description"],
                "steam_url":   meta["steam_url"],
                "price":       price,
                "steam_priority": item.get("priority", 999),
            })
        except Exception:
            enriched.append({
                "app_id":   app_id,
                "name":     f"App {app_id}",
                "priority": item.get("priority", 0),
            })

    return enriched


def map_steam_priority(steam_priority: int) -> str:
    """
    Map Steam's numeric wishlist position to our S/A/B/C system.
    Steam priority is 0-based position in the list (0 = most wanted).
    """
    if steam_priority <= 2:
        return "S"
    elif steam_priority <= 8:
        return "A"
    elif steam_priority <= 20:
        return "B"
    else:
        return "C"


def import_wishlist(
    steam_id64: str,
    api_key: str,
    country: str = "mx",
    on_progress: callable = None,
    skip_existing: bool = True,
) -> dict:
    """
    Full import: fetch wishlist, skip already-added games, add new ones.
    Returns {"added": n, "skipped": n, "errors": n, "total": n}.
    """
    import data.repository as repo

    existing_ids = {g.app_id for g in repo.get_all()}

    items = fetch_wishlist_with_details(
        steam_id64, api_key, country, on_progress=on_progress
    )

    added   = 0
    skipped = 0
    errors  = 0

    for item in items:
        app_id = item.get("app_id", "")
        if not app_id:
            continue

        if skip_existing and app_id in existing_ids:
            skipped += 1
            continue

        try:
            priority = map_steam_priority(item.get("steam_priority", 999))
            game = Game(
                id=0,
                name=item.get("name", f"App {app_id}"),
                app_id=app_id,
                steam_url=item.get("steam_url", f"https://store.steampowered.com/app/{app_id}"),
                genre=item.get("genre", ""),
                release_year=item.get("release_year", 0),
                developer=item.get("developer", ""),
                publisher=item.get("publisher", ""),
                categories=item.get("categories", ""),
                short_description=item.get("short_description", ""),
                priority=priority,
                status="Wishlist",
                price=item.get("price"),
                price_history=None,
                notes="Imported from Steam",
            )
            repo.add(game)
            added += 1
        except Exception:
            errors += 1

    return {
        "added":   added,
        "skipped": skipped,
        "errors":  errors,
        "total":   len(items),
    }


def get_player_summary(steam_id64: str, api_key: str) -> Optional[dict]:
    """Fetch basic profile info: name, avatar, profile URL."""
    try:
        resp = _SESSION.get(
            "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/",
            params={"key": api_key, "steamids": steam_id64},
            timeout=10,
        )
        players = resp.json().get("response", {}).get("players", [])
        if players:
            p = players[0]
            return {
                "name":       p.get("personaname", ""),
                "avatar_url": p.get("avatarmedium", ""),
                "profile_url":p.get("profileurl", ""),
                "steam_id":   steam_id64,
            }
    except Exception:
        pass
    return None
