"""
Discord price alerts — the server (pimpmysteam.com) checks Steam prices and
DMs you through the PimpMySteam bot; the app only links the account, sets
the toggles and uploads what to watch. All calls are blocking → run_async.

    status()                 GET  /alerts/settings → dict (also caches "linked")
    web_settings_url()       pimpmysteam.com › Settings › Alerts — Discord is linked there
                             (the app opens it and polls status() until linked)
    unlink()                 DELETE /discord/link  (the server forgets the watchlist)
    update(**toggles)        PUT  /alerts/settings  enabled · on_sale · at_low · daily_digest · sale_events
    send_test()              POST /alerts/test
    push_watchlist(force)    PUT  /alerts/watchlist — only while linked, only when it changed

What is uploaded: for each wishlist game its Steam app id, name, priority and
the all-time low this app knows (in your currency), plus your store region and
language. Nothing is uploaded unless Discord alerts are linked.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time

log = logging.getLogger("curator.alerts")

_DIGITS = re.compile(r"^\d{1,10}$")
_HASH_KEY = "alerts_watchlist_hash"
_LINKED_KEY = "discord_alerts_linked"
_STATUS_EVERY_S = 600           # re-ask the server at most every 10 min while not linked
_last_status_check = 0.0


def _api(path: str, method: str = "GET", body=None, timeout: int = 20) -> dict:
    from services.steamkustom_auth import api
    return api(path, method=method, json_body=body, timeout=timeout)


def is_linked_cached() -> bool:
    from ui.settings_loader import get_settings
    return bool(get_settings().get(_LINKED_KEY))


def _remember_linked(linked: bool) -> None:
    from ui.settings_loader import get_settings, save_settings
    if bool(get_settings().get(_LINKED_KEY)) != linked:
        save_settings({_LINKED_KEY: linked, **({} if linked else {_HASH_KEY: ""})})


def status() -> dict:
    s = _api("/alerts/settings")
    _remember_linked(bool(s.get("linked")))
    return s


def web_settings_url() -> str:
    """The website page where Discord is linked: the API host without "api."."""
    from urllib.parse import urlsplit
    from services.steamkustom_auth import get_api_url
    parts = urlsplit(get_api_url())
    host = parts.netloc
    site = f"{parts.scheme or 'https'}://{host[4:]}" if host.startswith("api.") else "https://pimpmysteam.com"
    return f"{site}/settings?tab=alerts"


def unlink() -> None:
    _api("/discord/link", "DELETE")
    _remember_linked(False)


def update(**toggles) -> dict:
    body = {k: bool(v) for k, v in toggles.items()
            if k in ("enabled", "on_sale", "at_low", "daily_digest", "sale_events")}
    return _api("/alerts/settings", "PUT", body)


def send_test() -> dict:
    return _api("/alerts/test", "POST")


def watchlist_payload() -> dict:
    import data.repository as repo
    from data.status import STATUS_WISHLIST, normalize_status
    from services import price_history
    from ui.settings_loader import get_settings
    s = get_settings()
    games = []
    for g in repo.get_all():
        if normalize_status(g.status) != STATUS_WISHLIST or not _DIGITS.match(str(g.app_id or "")):
            continue
        h = g.price_history
        low = h.all_time_low if (h and h.all_time_low and price_history.is_real_low(h, g.price)) else None
        games.append({"app_id": str(g.app_id), "name": (g.name or "")[:200],
                      "priority": g.priority if g.priority in ("S", "A", "B", "C") else None,
                      "low": round(float(low), 2) if low else None})
    games.sort(key=lambda x: x["app_id"])
    return {"country": (s.get("country") or "us").lower()[:2], "locale": s.get("locale") or "en",
            "games": games[:3000]}


def push_watchlist(force: bool = False) -> dict:
    """Upload the watchlist if linked and it changed since the last upload."""
    from services._http import ApiError
    from services.steamkustom_auth import get_token
    from ui.settings_loader import get_settings, save_settings
    global _last_status_check
    if not get_token():
        return {"skipped": "not linked"}
    if not is_linked_cached() and time.time() - _last_status_check > _STATUS_EVERY_S:
        # Discord may have been linked on pimpmysteam.com — ask the server.
        _last_status_check = time.time()
        try:
            status()
        except Exception as e:  # noqa: BLE001 — offline: try again later
            log.info("alerts status unavailable: %s", e)
    if not is_linked_cached():
        return {"skipped": "not linked"}
    body = watchlist_payload()
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    if not force and get_settings().get(_HASH_KEY) == digest:
        return {"skipped": "unchanged"}
    try:
        res = _api("/alerts/watchlist", "PUT", body, timeout=30)
    except ApiError as e:
        if e.status == 409:                     # unlinked from elsewhere
            _remember_linked(False)
            return {"skipped": "not linked"}
        raise
    save_settings({_HASH_KEY: digest})
    return res
