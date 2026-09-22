"""
Historical-low prices, two tiers:

1. IsThereAnyDeal (when an API key is set in Settings → "itad_key"):
   the real all-time low on Steam for the user's country. Batch friendly.
2. Local observation (always on): every price the app fetches is logged in
   <BASE_DIR>/price_log.json, so the lowest price *this app has seen* is
   available without any key. It starts empty and gets better with every
   "Refresh prices". `PriceHistory.source` tells the UI which tier answered.

The old SteamDB scraper was removed: Cloudflare blocks it and it returned
None for every game, which is why the advice panel never had data.

Docs: https://docs.isthereanydeal.com/
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from data.models import PriceHistory, PriceInfo
from services._http import SESSION

log = logging.getLogger("curator.history")

_API = "https://api.isthereanydeal.com"
_STEAM_SHOP_ID = 61
_lookup_cache: dict[str, Optional[str]] = {}       # steam appid → itad game id
_hist_cache: dict[str, tuple[Optional[PriceHistory], float]] = {}
_TTL = 6 * 3600
_BATCH = 100

SOURCE_ITAD     = "itad"
SOURCE_OBSERVED = "observed"


# ── settings ─────────────────────────────────────────────────────────────────

def get_key() -> str:
    from ui.settings_loader import get_settings
    return (get_settings().get("itad_key") or "").strip()


def is_configured() -> bool:
    return bool(get_key())


# ── tier 2: local observation log ────────────────────────────────────────────

_log_lock = threading.RLock()
_log_cache: Optional[dict] = None


def _log_path() -> Path:
    import config
    return config.BASE_DIR / "price_log.json"


def _load_log() -> dict:
    global _log_cache
    with _log_lock:
        if _log_cache is None:
            try:
                _log_cache = json.loads(_log_path().read_text(encoding="utf-8"))
                if not isinstance(_log_cache, dict):
                    _log_cache = {}
            except (OSError, ValueError):
                _log_cache = {}
        return _log_cache


def _save_log() -> None:
    with _log_lock:
        data = _log_cache or {}
        path = _log_path()
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            log.warning("price log not saved: %s", e)


def _observe_locked(app_id: str, price: PriceInfo, when: str) -> None:
    d = _load_log()
    key = f"{app_id}:{(price.currency or 'USD').upper()}"
    row = d.get(key) or {"low": None, "low_date": None, "low_discount": 0,
                         "last_sale_price": None, "last_sale_date": None, "samples": 0}
    row["samples"] = int(row.get("samples", 0)) + 1
    row["last_seen"] = when
    if row["low"] is None or price.current < float(row["low"]):
        row["low"] = round(float(price.current), 2)
        row["low_date"] = when
        row["low_discount"] = int(price.discount_pct or 0)
    if price.is_on_sale and price.discount_pct:
        row["last_sale_price"] = round(float(price.current), 2)
        row["last_sale_date"] = when
    d[key] = row


def observe(app_id: str, price: Optional[PriceInfo], when: Optional[str] = None) -> None:
    """Record one observed price (call after every successful price fetch)."""
    if price is None or price.current is None or price.current < 0:
        return
    with _log_lock:
        _observe_locked(str(app_id), price, when or date.today().isoformat())
    _save_log()


def observe_many(pairs: Iterable[tuple[str, Optional[PriceInfo]]]) -> None:
    """observe() for many games with a single disk write."""
    today = date.today().isoformat()
    with _log_lock:
        for app_id, price in pairs:
            if price is not None and price.current is not None and price.current >= 0:
                _observe_locked(str(app_id), price, today)
    _save_log()


def observed_history(app_id: str, currency: str) -> Optional[PriceHistory]:
    """Lowest price this app has seen for (app_id, currency), or None."""
    row = _load_log().get(f"{app_id}:{(currency or 'USD').upper()}")
    if not row or row.get("low") is None:
        return None
    return PriceHistory(
        all_time_low      = float(row["low"]),
        all_time_low_date = row.get("low_date"),
        all_time_discount = int(row.get("low_discount") or 0),
        last_sale_price   = row.get("last_sale_price"),
        last_sale_date    = row.get("last_sale_date"),
        source            = SOURCE_OBSERVED,
    )


# ── tier 1: IsThereAnyDeal ───────────────────────────────────────────────────

def _lookup_many(app_ids: list[str], key: str) -> dict[str, Optional[str]]:
    """steam appid → ITAD game id (POST /lookup/id/shop/61/v1, batched)."""
    out: dict[str, Optional[str]] = {}
    todo = [a for a in app_ids if a not in _lookup_cache]
    for a in app_ids:
        if a in _lookup_cache:
            out[a] = _lookup_cache[a]
    for i in range(0, len(todo), _BATCH):
        chunk = todo[i:i + _BATCH]
        try:
            r = SESSION.post(f"{_API}/lookup/id/shop/{_STEAM_SHOP_ID}/v1",
                             params={"key": key}, json=[f"app/{a}" for a in chunk], timeout=20)
            r.raise_for_status()
            mapping = r.json() or {}
        except Exception as e:  # noqa: BLE001
            log.warning("itad lookup batch failed: %s", e)
            mapping = {}
        for a in chunk:
            gid = mapping.get(f"app/{a}")
            _lookup_cache[a] = gid
            out[a] = gid
    return out


def _parse_low(row: dict) -> Optional[PriceHistory]:
    lows = row.get("lows") or []
    if not lows:
        return None
    low = lows[0]
    price = low.get("price", {}) or {}
    return PriceHistory(
        all_time_low      = float(price.get("amount", 0) or 0),
        all_time_low_date = (low.get("timestamp") or "")[:10] or None,
        all_time_discount = int(low.get("cut", 0) or 0),
        last_sale_price   = None,
        last_sale_date    = None,
        source            = SOURCE_ITAD,
    )


def _itad_many(app_ids: list[str], country: str, key: str) -> dict[str, Optional[PriceHistory]]:
    ids = _lookup_many(app_ids, key)
    by_gid = {gid: a for a, gid in ids.items() if gid}
    result: dict[str, Optional[PriceHistory]] = {a: None for a in app_ids}
    gids = list(by_gid)
    for i in range(0, len(gids), _BATCH):
        chunk = gids[i:i + _BATCH]
        try:
            r = SESSION.post(f"{_API}/games/storelow/v2",
                             params={"key": key, "country": country.upper(), "shops": _STEAM_SHOP_ID},
                             json=chunk, timeout=30)
            r.raise_for_status()
            rows = r.json() or []
        except Exception as e:  # noqa: BLE001
            log.warning("itad storelow batch failed: %s", e)
            rows = []
        for row in rows:
            a = by_gid.get(row.get("id"))
            if a:
                result[a] = _parse_low(row)
    return result


# ── public API ───────────────────────────────────────────────────────────────

def get_price_history(app_id: str, country: str = "MX", key: Optional[str] = None,
                      force: bool = False, currency: Optional[str] = None) -> Optional[PriceHistory]:
    """
    All-time low for *app_id*: ITAD when a key is configured (cached 6 h),
    else — or when ITAD knows nothing — the locally observed low.
    `currency` selects the observation bucket (defaults to any currency seen).
    """
    app_id = str(app_id)
    key = key or get_key()
    if key:
        ck = f"{app_id}:{country}"
        entry = _hist_cache.get(ck)
        if entry and not force and time.time() - entry[1] < _TTL:
            hist = entry[0]
        else:
            hist = _itad_many([app_id], country, key).get(app_id)
            _hist_cache[ck] = (hist, time.time())
        if hist:
            return hist
    return _observed_any(app_id, currency)


def _observed_any(app_id: str, currency: Optional[str]) -> Optional[PriceHistory]:
    if currency:
        return observed_history(app_id, currency)
    prefix = f"{app_id}:"
    best = None
    for k in list(_load_log().keys()):
        if k.startswith(prefix):
            h = observed_history(app_id, k[len(prefix):])
            if h and (best is None or h.all_time_low < best.all_time_low):
                best = h
    return best


def get_price_histories(games: list, country: str, force: bool = False) -> dict[str, Optional[PriceHistory]]:
    """
    Histories for many Game objects in as few requests as possible.
    ITAD for everything it knows, observed log for the rest.
    """
    ids = [str(g.app_id) for g in games if g.app_id and not str(g.app_id).startswith("unknown")]
    out: dict[str, Optional[PriceHistory]] = {}
    key = get_key()
    if key and ids:
        want = ids if force else [a for a in ids
                                  if not (_hist_cache.get(f"{a}:{country}")
                                          and time.time() - _hist_cache[f"{a}:{country}"][1] < _TTL)]
        fetched = _itad_many(want, country, key) if want else {}
        now = time.time()
        for a in want:
            _hist_cache[f"{a}:{country}"] = (fetched.get(a), now)
        for a in ids:
            out[a] = _hist_cache.get(f"{a}:{country}", (None, 0))[0]
    for g in games:
        a = str(g.app_id)
        if out.get(a) is None:
            out[a] = _observed_any(a, g.price.currency if g.price else None)
    return out


def merge(existing: Optional[PriceHistory], fresh: Optional[PriceHistory]) -> Optional[PriceHistory]:
    """Never replace real ITAD data with an observation; otherwise take the lower low."""
    if fresh is None:
        return existing
    if existing is None:
        return fresh
    if existing.source == SOURCE_ITAD and fresh.source != SOURCE_ITAD:
        return existing
    if fresh.source == SOURCE_ITAD:
        return fresh
    return fresh if fresh.all_time_low <= existing.all_time_low else existing
