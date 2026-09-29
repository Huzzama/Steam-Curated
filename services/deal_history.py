"""
Deal history per game — the raw material of the prediction algorithm.

Only *when* a game was discounted and *by how much* (%) is stored, never an
absolute price. Steam applies the same % in every region, so the history is
currency-independent and every price the UI shows is computed from the
game's base price in the user's own currency.

Source: the Steam store itself — every price this app fetches ("seen"),
including the automatic daily check (services.price_watch). Events imported
by older versions ("itad") are kept and used like any other.

Store: <BASE_DIR>/deal_history.json
    {"version": 1, "games": {"<appid>": {"events": [["2025-06-26", 50, "seen"], ...]}}}
An event is a price change: (ISO date, discount %, source). cut 0 = back to
full price.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("curator.deals")


Event = tuple[str, int, str]            # (iso date, cut %, source)

_lock = threading.RLock()
_store: Optional[dict] = None


# ── storage ──────────────────────────────────────────────────────────────────

def _path() -> Path:
    import config
    return config.BASE_DIR / "deal_history.json"


def _load() -> dict:
    global _store
    with _lock:
        if _store is None:
            try:
                data = json.loads(_path().read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("games"), dict):
                    raise ValueError("bad shape")
                _store = data
            except (OSError, ValueError):
                _store = {"version": 1, "games": {}}
        return _store


def _save() -> None:
    with _lock:
        data = _load()
        path = _path()
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            log.warning("deal history not saved: %s", e)


def reset_cache() -> None:
    """Forget the in-memory copy (tests / after a Drive restore)."""
    global _store
    with _lock:
        _store = None


def _game(app_id: str) -> dict:
    return _load()["games"].setdefault(str(app_id), {"events": []})


def events(app_id: str) -> list[Event]:
    """All known price changes for *app_id*, oldest first."""
    with _lock:
        g = _load()["games"].get(str(app_id))
        evs = [tuple(e) for e in (g or {}).get("events", []) if len(e) == 3]
    evs.sort(key=lambda e: (e[0], 0 if e[2] == "itad" else 1))
    return evs  # type: ignore[return-value]


# ── source "seen": observations from the Steam store ─────────────────────────

def _record_locked(app_id: str, cut: int, when: str) -> bool:
    g = _game(app_id)
    evs = g["events"]
    last_seen = None
    for e in reversed(evs):
        if e[0] <= when:
            last_seen = e
            break
    if last_seen is not None and int(last_seen[1]) == cut:
        return False                    # no change → nothing to store
    if any(e[0] == when and e[2] == "seen" for e in evs):
        for e in evs:
            if e[0] == when and e[2] == "seen":
                e[1] = cut
        return True
    evs.append([when, cut, "seen"])
    evs.sort(key=lambda e: e[0])
    return True


def record(app_id: str, cut: int, when: Optional[str] = None) -> None:
    """Store an observed discount (0 = full price) if it differs from the last one."""
    if not app_id or str(app_id).startswith("unknown"):
        return
    with _lock:
        changed = _record_locked(str(app_id), int(cut or 0), when or date.today().isoformat())
    if changed:
        _save()


def record_many(pairs: Iterable[tuple[str, int]]) -> None:
    today = date.today().isoformat()
    changed = False
    with _lock:
        for app_id, cut in pairs:
            if app_id and not str(app_id).startswith("unknown"):
                changed |= _record_locked(str(app_id), int(cut or 0), today)
    if changed:
        _save()


# ── coverage ─────────────────────────────────────────────────────────────────

def coverage_start(app_id: str) -> Optional[str]:
    """ISO date from which the history is complete (legacy import window or first observation)."""
    with _lock:
        g = _load()["games"].get(str(app_id)) or {}
        if g.get("itad_since"):
            return g["itad_since"]
        evs = g.get("events") or []
        return evs[0][0] if evs else None


def summary() -> tuple[int, int]:
    """(games with at least one recorded sale, total sales recorded)."""
    from services.deal_predictor import episodes_from
    games = sales = 0
    with _lock:
        ids = list(_load()["games"].keys())
    for app_id in ids:
        n = len(episodes_from(events(app_id)))
        if n:
            games += 1
            sales += n
    return games, sales
