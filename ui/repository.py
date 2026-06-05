"""
Repository with in-memory cache + O(1) indexes.
Reads JSON once, keeps everything in RAM.
"""
import json
from typing import Optional
from dataclasses import asdict
from data.models import Game, PriceInfo, PriceHistory


def _get_db_path():
    """Lazy path — evaluated after config is fully initialized."""
    from config import BASE_DIR
    return BASE_DIR / "wishlist.json"


# ── In-memory cache + indexes ─────────────────────────────────────────────────
_cache:     Optional[list[dict]] = None
_id_index:  Optional[dict]       = None   # app_id -> dict  O(1)
_set_index: Optional[set]        = None   # set of app_ids  O(1)


def _load() -> list[dict]:
    global _cache, _id_index, _set_index
    if _cache is not None:
        return _cache
    p = _get_db_path()
    if not p.exists():
        _cache = []; _id_index = {}; _set_index = set()
        return _cache
    with open(p, encoding="utf-8") as f:
        _cache = json.load(f)
    _id_index  = {str(d["app_id"]): d for d in _cache}
    _set_index = set(_id_index)
    return _cache


def _save(data: list[dict]) -> None:
    global _cache, _id_index, _set_index
    _cache     = data
    _id_index  = {str(d["app_id"]): d for d in data}
    _set_index = set(_id_index)
    with open(_get_db_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _invalidate():
    global _cache, _id_index, _set_index
    _cache = _id_index = _set_index = None


# ── Converters ────────────────────────────────────────────────────────────────

def _to_game(d: dict) -> Game:
    price = PriceInfo(**d["price"])         if d.get("price")         else None
    hist  = PriceHistory(**d["price_history"]) if d.get("price_history") else None
    return Game(
        id=d["id"], name=d["name"], app_id=d["app_id"],
        steam_url=d.get("steam_url", ""),
        genre=d.get("genre", ""), release_year=d.get("release_year", 0),
        developer=d.get("developer", ""), publisher=d.get("publisher", ""),
        categories=d.get("categories", ""),
        short_description=d.get("short_description", ""),
        priority=d.get("priority", "C"), status=d.get("status", "Wishlist"),
        price=price, price_history=hist,
        personal_rating=d.get("personal_rating"),
        notes=d.get("notes", ""),
        cover_path=d.get("cover_path"),
        date_added=d.get("date_added", ""),
    )


def _from_game(g: Game) -> dict:
    return asdict(g)


# ── Public API ────────────────────────────────────────────────────────────────

def get_all() -> list[Game]:
    return list(_to_game(d) for d in _load())


def get_by_id(game_id: int) -> Optional[Game]:
    for d in _load():
        if d["id"] == game_id:
            return _to_game(d)
    return None


def get_by_app_id(app_id: str) -> Optional[Game]:
    """O(1) lookup by app_id."""
    _load()
    d = _id_index.get(str(app_id))
    return _to_game(d) if d else None


def exists(app_id: str) -> bool:
    """O(1) membership check."""
    _load()
    return str(app_id) in _set_index


def add(game: Game) -> Game:
    db      = _load()
    next_id = max((d["id"] for d in db), default=0) + 1
    game.id = next_id
    db.append(_from_game(game))
    _save(db)
    return game


def update(game: Game) -> bool:
    db = _load()
    for i, d in enumerate(db):
        if d["id"] == game.id:
            db[i] = _from_game(game)
            _save(db)
            return True
    return False


def delete(game_id: int) -> bool:
    db     = _load()
    new_db = [d for d in db if d["id"] != game_id]
    if len(new_db) == len(db):
        return False
    _save(new_db)
    return True


def get_on_sale() -> list[Game]:
    return [g for g in get_all() if g.price and g.price.is_on_sale]


def get_recent(limit: int = 20) -> list[Game]:
    return sorted(get_all(), key=lambda g: g.date_added, reverse=True)[:limit]


def get_by_priority(priority: str) -> list[Game]:
    return [g for g in get_all() if g.priority == priority]