"""
All-time lows, always in the user's currency.

The low is derived from the game's *deal history* (services.deal_history:
dates + discount % of every price this app sees on the Steam store) applied
to the game's base price, plus the lowest price actually observed in that
currency (<BASE_DIR>/price_log.json). The prediction itself lives in
services.deal_predictor; the daily price check in services.price_watch.
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

log = logging.getLogger("curator.history")


SOURCE_HISTORY  = "history"     # derived from the deal history (record % × base price)
SOURCE_OBSERVED = "observed"    # lowest price this app has seen in that currency
SOURCE_ITAD_LEGACY = "itad"     # old absolute ITAD lows — may be in the wrong currency
SOURCE_ITAD = SOURCE_HISTORY    # backwards-compatible name


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
    from services import deal_history
    deal_history.record(str(app_id), int(price.discount_pct or 0) if price.is_on_sale else 0, when)


def observe_many(pairs: Iterable[tuple[str, Optional[PriceInfo]]]) -> None:
    """observe() for many games with a single disk write."""
    today = date.today().isoformat()
    pairs = [(str(a), p) for a, p in pairs if p is not None and p.current is not None and p.current >= 0]
    with _log_lock:
        for app_id, price in pairs:
            _observe_locked(app_id, price, today)
    _save_log()
    from services import deal_history
    deal_history.record_many((a, int(p.discount_pct or 0) if p.is_on_sale else 0) for a, p in pairs)


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


# ── deal history → all-time low in the user's currency ──────────────────────

def derive(app_id: str, price: Optional[PriceInfo]) -> Optional[PriceHistory]:
    """
    All-time low for *app_id* expressed in *price*'s currency:
      deepest cut in the deal history (ITAD + observations) applied to the
      game's base price, or the lowest price this app actually saw in that
      currency — whichever is lower.
    """
    from services import deal_history, deal_predictor
    app_id = str(app_id)
    cur = (price.currency if price else None)
    obs = observed_history(app_id, cur) if cur else _observed_any(app_id, None)
    evs = deal_history.events(app_id)
    st = deal_predictor.compute_stats(evs, deal_history.coverage_start(app_id)) if evs else None
    hist: Optional[PriceHistory] = None
    if st and st.max_cut and price and price.base:
        last = st.last
        hist = PriceHistory(
            all_time_low      = round(price.base * (1 - st.max_cut / 100), 2),
            all_time_low_date = st.max_cut_date.isoformat() if st.max_cut_date else None,
            all_time_discount = st.max_cut,
            last_sale_price   = round(price.base * (1 - last.cut / 100), 2) if last else None,
            last_sale_date    = last.start.isoformat() if last else None,
            source            = SOURCE_HISTORY if st.source == "itad" else SOURCE_OBSERVED,
        )
    if obs and not is_real_low(obs, price):
        obs = None                       # lowest price seen = full price → not a deal
    if obs and (hist is None or obs.all_time_low < hist.all_time_low - 0.005):
        if hist is not None:
            obs.last_sale_price = obs.last_sale_price or hist.last_sale_price
            obs.last_sale_date = obs.last_sale_date or hist.last_sale_date
        hist = obs
    return hist


def is_real_low(h: PriceHistory, price: Optional[PriceInfo]) -> bool:
    """A low only counts when it was a discount (or clearly under today's base price)."""
    if h.all_time_discount and h.all_time_discount > 0:
        return True
    base = price.base if price and price.base else None
    return bool(base and h.all_time_low < base * 0.95)


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


# ── public API ───────────────────────────────────────────────────────────────

def get_price_history(app_id: str, country: str = "US", key: Optional[str] = None,
                      force: bool = False, currency: Optional[str] = None,
                      price: Optional[PriceInfo] = None) -> Optional[PriceHistory]:
    """All-time low of *app_id* in the game's currency, from its deal history.
    (`country`, `key`, `force` are ignored — kept for call-site compatibility.)"""
    app_id = str(app_id)
    if price is None and currency:
        return observed_history(app_id, currency)
    return derive(app_id, price)


def get_price_histories(games: list, country: str = "US", force: bool = False,
                        on_progress=None) -> dict[str, Optional[PriceHistory]]:
    """Derive every game's low from local data (no network)."""
    return {str(g.app_id): derive(str(g.app_id), g.price) for g in games if g.app_id}


def merge(existing: Optional[PriceHistory], fresh: Optional[PriceHistory]) -> Optional[PriceHistory]:
    """The derived history always wins. Old absolute ITAD lows (source "itad",
    possibly in the wrong currency) are dropped when nothing replaces them."""
    if fresh is not None:
        return fresh
    if existing is not None and (existing.source == SOURCE_ITAD_LEGACY
                                 or not existing.all_time_discount):
        return None                      # wrong currency, or a full-price "low"
    return existing


def recompute_all() -> int:
    """Re-derive every game's stored low from local data (no network). Fixes lows
    saved by older versions in the wrong currency. Returns games changed."""
    import data.repository as repo
    changed = []
    for g in repo.get_all():
        if not g.app_id:
            continue
        new = merge(g.price_history, derive(str(g.app_id), g.price))
        if new != g.price_history:
            g.price_history = new
            changed.append(g)
    if changed:
        repo.update_many(changed)
    return len(changed)
