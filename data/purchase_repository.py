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
from dataclasses import asdict, fields

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


_FIELDS = {f.name for f in fields(Purchase)}


def _from(d: dict) -> Purchase:
    return Purchase(**{k: v for k, v in d.items() if k in _FIELDS})


def get_all() -> list[Purchase]:
    return [_from(d) for d in _load()]


def get_by_app_id(app_id: str) -> Optional[Purchase]:
    for d in _load():
        if d["app_id"] == app_id:
            return _from(d)
    return None


def add(purchase: Purchase) -> Purchase:
    """Insert (or replace the entry for the same app_id) at the top."""
    with _lock:
        db = [d for d in _load() if d["app_id"] != purchase.app_id]
        db.insert(0, asdict(purchase))
        _save(db)
    return purchase


def update(purchase: Purchase) -> None:
    """Rewrite an existing entry in place (keeps its position)."""
    with _lock:
        db = [asdict(purchase) if d["app_id"] == purchase.app_id else d for d in _load()]
        _save(db)


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