"""
Fetch and import the user's Steam wishlist.

The wishlist comes from the PimpMySteam backend (GET /steam/me/wishlist) for
the Steam account linked to the connected PimpMySteam user — the app never
sees a Steam Web API key. Store details are then fetched per game from the
public Steam store API.

`steam_id64` / `api_key` parameters are kept for call-site compatibility and
ignored.
"""
import logging
from typing import Optional
from data.models import Game, PriceInfo
from datetime import datetime

log = logging.getLogger("curator.wishlist")


def fetch_wishlist(steam_id64: str = None, api_key: str = None, country: str = "mx") -> list[dict]:
    """
    The user's Steam wishlist via the backend.
    Returns [{"appid", "priority", "date_added", "name"}, …].
    Raises services._http.ApiError / Unreachable.
    """
    from services.steamkustom_auth import get_wishlist
    return get_wishlist()


def fetch_wishlist_with_details(
    steam_id64: str = None,
    api_key: str = None,
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
            # Previously this silently dropped the item with no trace —
            # if Steam ever returns a wishlist entry without an "appid"
            # (seen with delisted/removed apps), the game would vanish
            # from the import entirely with no way to tell why the final
            # count didn't match the Steam wishlist count. Still include
            # a placeholder entry so it shows up (with a generic name)
            # instead of disappearing, and log it so it's traceable.
            log.warning("item %d/%d has no appid: %s", i + 1, total, item)
            enriched.append({
                "app_id":   f"unknown_{i}",
                "name":     item.get("name") or f"Unknown wishlist item #{i+1}",
                "priority": item.get("priority", 0),
            })
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
    Map Steam's wishlist priority to our S/A/B/C system.

    IWishlistService returns the user's manual ordering as `priority`
    (1 = top of the list); games the user never ordered come back as 0.
    Those must NOT become "S" — they land in "B" (the neutral tier).
    """
    if steam_priority <= 0:
        return "B"
    if steam_priority <= 3:
        return "S"
    elif steam_priority <= 10:
        return "A"
    elif steam_priority <= 25:
        return "B"
    else:
        return "C"


def import_wishlist(
    steam_id64: str = None,
    api_key: str = None,
    country: str = "mx",
    on_progress: callable = None,
    skip_existing: bool = True,
) -> dict:
    """
    Full import: fetch wishlist, skip already-added games, add new ones.
    Returns {"added": n, "skipped": n, "errors": n, "total": n}.
    """
    import data.repository as repo

    # Use O(1) set index from repo instead of loading all games
    try:
        repo._load()
        existing_ids = repo._set_index or {g.app_id for g in repo.get_all()}
    except Exception:
        existing_ids = {g.app_id for g in repo.get_all()}

    items = fetch_wishlist_with_details(
        steam_id64, api_key, country, on_progress=on_progress
    )

    added    = 0
    skipped  = 0
    errors   = 0
    dropped  = 0   # items with no usable app_id — should be 0 after the fix above
    new_games: list[Game] = []

    for item in items:
        app_id = item.get("app_id", "")
        if not app_id:
            dropped += 1
            log.warning("dropping item with no app_id: %s", item)
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
            new_games.append(game)
            added += 1
        except Exception as e:  # noqa: BLE001
            errors += 1
            log.warning("failed to build %s: %s", item.get('name', app_id), e)

    # one disk write for the whole import
    if new_games:
        repo.add_many(new_games)

    total_steam = len(items)
    accounted   = added + skipped + errors + dropped
    if accounted != total_steam:
        # This should never happen after the fix above, but log loudly if
        # it ever does again so a future "62 vs 65" report is traceable
        # instead of a mystery.
        log.warning("accounted %d != Steam total %d (added=%d skipped=%d errors=%d dropped=%d)",
                    accounted, total_steam, added, skipped, errors, dropped)

    return {
        "added":   added,
        "skipped": skipped,
        "errors":  errors,
        "dropped": dropped,
        "total":   len(items),
    }


def get_player_summary(steam_id64: str = None, api_key: str = None) -> Optional[dict]:
    """Basic profile info (name, avatar, profile URL) via the backend."""
    from services.steamkustom_auth import get_player_summary as _summary
    return _summary()
