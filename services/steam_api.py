import requests
from typing import Optional
from data.models import PriceInfo

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "SteamLibraryCurator/1.0"})
TIMEOUT = 10

# Map country code → Steam language for descriptions
_CC_TO_LANG = {
    "mx": "spanish", "es": "spanish", "ar": "spanish",
    "br": "brazilian", "us": "english", "gb": "english",
    "jp": "japanese", "fr": "french", "de": "german",
    "kr": "koreana", "cn": "schinese",
}

def _lang(cc: str) -> str:
    return _CC_TO_LANG.get(cc.lower(), "english")


def search_games(query: str, limit: int = 8, cc: str = "mx") -> list[dict]:
    """Search Steam and return up to `limit` results with prices in the given currency."""
    try:
        resp = _SESSION.get(
            "https://store.steampowered.com/api/storesearch/",
            params={"term": query, "l": _lang(cc), "cc": cc},
            timeout=TIMEOUT,
        )
        data = resp.json()
        items = data.get("items", [])
        results = []
        for item in items[:limit]:
            price_raw = item.get("price", {})
            results.append({
                "id":         str(item.get("id", "")),
                "name":       item.get("name", ""),
                "type":       item.get("type", ""),
                "tiny_image": item.get("tiny_image", ""),
                "price":      price_raw.get("final", 0) / 100 if price_raw else None,
                "currency":   price_raw.get("currency", "") if price_raw else "",
            })
        return results
    except Exception:
        return []


def search_app_id(query: str, cc: str = "mx") -> Optional[str]:
    results = search_games(query, limit=1, cc=cc)
    return results[0]["id"] if results else None


def get_app_details(app_id: str, country: str = "mx") -> Optional[dict]:
    """Fetch full app details from Steam Store API in the correct currency."""
    try:
        resp = _SESSION.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": app_id, "cc": country, "l": _lang(country)},
            timeout=TIMEOUT,
        )
        data = resp.json()
        app_data = data.get(str(app_id), {})
        if not app_data.get("success"):
            return None
        return app_data.get("data", {})
    except Exception:
        return None


def parse_metadata(data: dict) -> dict:
    genres     = [g["description"] for g in data.get("genres", [])]
    categories = [c["description"] for c in data.get("categories", [])]
    developers = data.get("developers", [])
    publishers = data.get("publishers", [])
    release    = data.get("release_date", {})

    return {
        "name":              data.get("name", ""),
        "genre":             ", ".join(genres[:3]),
        "release_year":      _parse_year(release.get("date", "")),
        "developer":         ", ".join(developers[:2]),
        "publisher":         ", ".join(publishers[:2]),
        "categories":        ", ".join(categories[:5]),
        "short_description": data.get("short_description", ""),
        "steam_url":         f"https://store.steampowered.com/app/{data.get('steam_appid', '')}",
        "is_released":       not release.get("coming_soon", False),
    }


def parse_price(data: dict) -> Optional[PriceInfo]:
    price_data = data.get("price_overview")
    if not price_data:
        return None
    return PriceInfo(
        current      = price_data.get("final",            0) / 100,
        base         = price_data.get("initial",          0) / 100,
        currency     = price_data.get("currency",      "USD"),
        discount_pct = price_data.get("discount_percent",  0),
        is_on_sale   = price_data.get("discount_percent",  0) > 0,
    )


def refresh_price(app_id: str, country: str = "mx") -> Optional[PriceInfo]:
    """Quick price-only refresh without fetching full metadata."""
    data = get_app_details(app_id, country=country)
    return parse_price(data) if data else None


def _parse_year(date_str: str) -> int:
    import re
    match = re.search(r"\b(19|20)\d{2}\b", date_str)
    return int(match.group()) if match else 0