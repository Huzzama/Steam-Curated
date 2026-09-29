"""
Automatic daily price check — this is what builds each game's deal history.

Every price the app fetches from the Steam store is recorded as a deal event
(services.deal_history). Checking the whole wishlist once a day means every
sale gets logged — start date, discount % and when it ended — without any
third-party service. The longer the app is used, the better the predictions.

    is_due()            → True when the last check is older than CHECK_EVERY_H
    last_check()        → unix time of the last completed check (0 = never)
    check_now(progress) → {"checked", "failed", "on_sale", "new_sales": [names]}
                          blocking — call it from a worker (ui.async_bridge /
                          a thread), never from the GUI thread.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("curator.watch")

CHECK_EVERY_H = 20              # "daily", with slack so a fixed daily launch always counts
_running = threading.Lock()


def last_check() -> float:
    from ui.settings_loader import get_settings
    try:
        return float(get_settings().get("last_price_check") or 0)
    except (TypeError, ValueError):
        return 0.0


def is_due(now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    return now - last_check() >= CHECK_EVERY_H * 3600


def is_running() -> bool:
    return _running.locked()


def _watched(games: list) -> list:
    """Games whose price matters: on the wishlist and with a real Steam app id."""
    return [g for g in games
            if g.app_id and not str(g.app_id).startswith("unknown")
            and (g.status or "Wishlist") not in ("Comprado", "Purchased", "Archivado", "Archived")]


def check_now(on_progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Fetch every wishlist price from Steam (records deal events + saves prices)."""
    if not _running.acquire(blocking=False):
        return {"checked": 0, "failed": 0, "on_sale": 0, "new_sales": [], "skipped": True}
    try:
        import data.repository as repo
        from services.steam_api import bulk_refresh_prices
        from ui.settings_loader import get_settings, save_settings

        country = (get_settings().get("country") or "mx").lower()
        games = _watched(repo.get_all())
        before = {str(g.app_id): bool(g.price and g.price.is_on_sale) for g in games}

        done = threading.Event()
        box: dict = {}

        def _done(updated, unchanged, failed):
            box.update(updated=updated, unchanged=unchanged, failed=failed)
            done.set()

        bulk_refresh_prices(games, country=country,
                            on_progress=(lambda c, n, _name: on_progress(c, n)) if on_progress else None,
                            on_done=_done, max_workers=6, force=True)
        done.wait(timeout=600)

        new_sales = [g.name for g in games
                     if g.price and g.price.is_on_sale and not before.get(str(g.app_id))]
        result = {
            "checked":   len(games) - int(box.get("failed", 0)),
            "failed":    int(box.get("failed", 0)),
            "on_sale":   sum(1 for g in games if g.price and g.price.is_on_sale),
            "new_sales": new_sales,
        }
        if games and result["checked"] == 0:
            log.info("price check: every request failed (offline?) — will retry later")
            return result
        save_settings({"last_price_check": int(time.time())})
        log.info("price check: %s", result)
        return result
    finally:
        _running.release()
