"""
Purchase history repository.
Stores in purchases.json — separate from wishlist.json.
"""
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional
from data.models import Purchase

log = logging.getLogger("curator.purchases")
_lock = threading.RLock()          # writes from the UI thread + reads from bundle workers


def _get_db_path():
    from config import BASE_DIR
    return BASE_DIR / "purchases.json"
_cache: Optional[list[dict]] = None


def _load() -> list[dict]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = _get_db_path()
        if not path.exists():
            _cache = []
            return _cache
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _cache = data if isinstance(data, list) else []
        except Exception as e:  # noqa: BLE001
            log.error("purchases.json unreadable (%s) — using backup", e)
            try:
                with open(path.with_suffix(".json.bak"), encoding="utf-8") as f:
                    _cache = json.load(f)
            except Exception:  # noqa: BLE001
                _cache = []
        return _cache


def _save(data: list[dict]):
    global _cache
    with _lock:
        _cache = data
        from data.repository import _write_json
        _write_json(_get_db_path(), data)


def get_all() -> list[Purchase]:
    return [Purchase(**d) for d in _load()]


def get_by_app_id(app_id: str) -> Optional[Purchase]:
    for d in _load():
        if d["app_id"] == app_id:
            return Purchase(**d)
    return None


def add(purchase: Purchase) -> Purchase:
    db = _load()
    # Remove existing entry for same app_id (re-purchase / update)
    db = [d for d in db if d["app_id"] != purchase.app_id]
    db.insert(0, {
        "app_id":       purchase.app_id,
        "name":         purchase.name,
        "purchased_at": purchase.purchased_at,
        "price_paid":   purchase.price_paid,
        "base_price":   purchase.base_price,
        "currency":     purchase.currency,
        "discount_pct": purchase.discount_pct,
        "edition":      purchase.edition,
        "saved":        purchase.saved,
    })
    _save(db)
    return purchase


def delete(app_id: str):
    db = _load()
    _save([d for d in db if d["app_id"] != app_id])


def total_spent() -> float:
    return sum(p.price_paid for p in get_all())


def total_base() -> float:
    return sum(p.base_price for p in get_all())


def total_saved() -> float:
    return sum(p.saved for p in get_all())


def invalidate():
    global _cache
    _cache = None