"""
Smart buy recommendation engine.

Combines:
- Current price vs historical low (from SteamDB)
- Sale calendar patterns (which sales historically include this genre/publisher)
- Time of year proximity to known sales

Returns a structured recommendation with reasoning and estimated next sale date.
"""
from datetime import date, datetime, timedelta
from typing import Optional
from data.models import Game, PriceInfo, PriceHistory
from config import STEAM_SALE_EVENTS

# ── Publisher sale patterns ────────────────────────────────────────────────────
# Based on historical Steam sale data — which publishers discount heavily
# and during which seasonal sales
PUBLISHER_PATTERNS: dict[str, dict] = {
    # Publisher name fragment → typical discount % and preferred sales
    "bandai namco":    {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "capcom":          {"max_discount": 80, "preferred_sales": ["summer", "winter", "spring"]},
    "square enix":     {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "atlus":           {"max_discount": 50, "preferred_sales": ["summer", "winter"]},
    "sega":            {"max_discount": 75, "preferred_sales": ["summer", "winter", "spring"]},
    "bethesda":        {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "ubisoft":         {"max_discount": 85, "preferred_sales": ["summer", "winter", "black_friday"]},
    "ea":              {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "2k":              {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "activision":      {"max_discount": 67, "preferred_sales": ["summer", "winter"]},
    "konami":          {"max_discount": 70, "preferred_sales": ["summer", "winter"]},
    "warner":          {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "505 games":       {"max_discount": 75, "preferred_sales": ["summer", "winter", "spring"]},
    "devolver":        {"max_discount": 90, "preferred_sales": ["summer", "winter", "spring"]},
    "paradox":         {"max_discount": 75, "preferred_sales": ["summer", "winter", "spring"]},
    "annapurna":       {"max_discount": 70, "preferred_sales": ["summer", "winter", "spring"]},
    "focus":           {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "thq nordic":      {"max_discount": 80, "preferred_sales": ["summer", "winter", "spring"]},
    "team17":          {"max_discount": 75, "preferred_sales": ["summer", "winter", "spring"]},
}

# Sale key fragments that map to friendly names
SALE_FRIENDLY: dict[str, str] = {
    "summer":      "Summer Sale",
    "winter":      "Winter Sale",
    "spring":      "Spring Sale",
    "autumn":      "Autumn Sale",
    "halloween":   "Halloween Sale",
    "black_friday":"Black Friday",
    "lunar":       "Lunar New Year Sale",
}


def get_recommendation(game: Game) -> dict:
    """
    Returns a structured recommendation dict:
    {
        "verdict":       "wait" | "buy_now" | "good_deal" | "no_data",
        "headline":      str,   # short one-liner
        "reason":        str,   # explanation
        "next_sale":     str | None,   # "Summer Sale 2026 (Jun 25)"
        "next_sale_date":str | None,   # ISO date
        "est_discount":  int | None,   # estimated % during that sale
        "est_price":     float | None, # estimated sale price
        "confidence":    str,   # "high" | "medium" | "low"
    }
    """
    price   = game.price
    history = game.price_history

    # No data at all
    if not price:
        return _no_data()

    today       = date.today()
    diff_pct    = game.price_diff_pct    # % above historical low (None if no history)
    publisher   = (game.publisher or "").lower()
    pub_pattern = _match_publisher(publisher)

    # ── Already at or near historical low ────────────────────────────────────
    if diff_pct is not None and diff_pct <= 5:
        return {
            "verdict":        "buy_now",
            "headline":       "Buy now — at historical low",
            "reason":         (f"Current price ${price.current:,.0f} {price.currency} "
                               f"is at or within 5% of the all-time low "
                               f"(${history.all_time_low:,.0f})."),
            "next_sale":      None,
            "next_sale_date": None,
            "est_discount":   price.discount_pct or 0,
            "est_price":      price.current,
            "confidence":     "high",
        }

    # ── Currently on sale but not at low ─────────────────────────────────────
    if price.is_on_sale and diff_pct is not None and diff_pct <= 25:
        return {
            "verdict":        "good_deal",
            "headline":       f"Good deal — {price.discount_pct}% off",
            "reason":         (f"It's on sale now at ${price.current:,.0f} {price.currency}. "
                               f"Historical low is ${history.all_time_low:,.0f} "
                               f"— you'd save ${history.all_time_low - price.current + abs(history.all_time_low - price.current):,.0f} "
                               f"more waiting, but this is already a solid discount."),
            "next_sale":      None,
            "next_sale_date": None,
            "est_discount":   price.discount_pct,
            "est_price":      price.current,
            "confidence":     "high",
        }

    # ── Find next likely sale ─────────────────────────────────────────────────
    next_event = _next_relevant_sale(today, pub_pattern)

    if next_event is None:
        # No upcoming sale found — generic advice
        if diff_pct is not None and diff_pct > 30:
            return {
                "verdict":        "wait",
                "headline":       "Wait for a sale",
                "reason":         (f"Current price (${price.current:,.0f}) is "
                                   f"{diff_pct:.0f}% above the historical low "
                                   f"(${history.all_time_low:,.0f} {price.currency})."),
                "next_sale":      None,
                "next_sale_date": None,
                "est_discount":   pub_pattern["max_discount"] if pub_pattern else None,
                "est_price":      _est_price(price.base, pub_pattern),
                "confidence":     "low",
            }
        return _no_data()

    # Build estimated sale price
    est_discount = pub_pattern["max_discount"] if pub_pattern else _guess_discount(game)
    est_price    = round(price.base * (1 - est_discount / 100), 2)
    days_away    = (datetime.strptime(next_event["start"], "%Y-%m-%d").date() - today).days

    # Format event name
    event_name = _event_name(next_event["key"])
    event_date = datetime.strptime(next_event["start"], "%Y-%m-%d").strftime("%b %d")
    sale_label = f"{event_name} ({event_date})"

    reason_parts = [
        f"${price.current:,.0f} {price.currency} is {diff_pct:.0f}% above the historical low."
        if diff_pct is not None else
        f"Current price: ${price.current:,.0f} {price.currency}.",
    ]
    if pub_pattern:
        reason_parts.append(
            f"{game.publisher} typically discounts up to {pub_pattern['max_discount']}% "
            f"during seasonal sales."
        )
    reason_parts.append(
        f"The {event_name} starts in {days_away} day{'s' if days_away != 1 else ''} "
        f"— estimated price around ${est_price:,.0f}."
    )

    return {
        "verdict":        "wait",
        "headline":       f"Wait — likely on sale in {days_away} days",
        "reason":         " ".join(reason_parts),
        "next_sale":      sale_label,
        "next_sale_date": next_event["start"],
        "est_discount":   est_discount,
        "est_price":      est_price,
        "confidence":     "high" if pub_pattern else "medium",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _no_data() -> dict:
    return {
        "verdict": "no_data", "headline": "No price data available",
        "reason": "Add a Steam API key in Settings to get price history.",
        "next_sale": None, "next_sale_date": None,
        "est_discount": None, "est_price": None, "confidence": "low",
    }


def _match_publisher(publisher_lower: str) -> Optional[dict]:
    for key, data in PUBLISHER_PATTERNS.items():
        if key in publisher_lower:
            return data
    return None


def _next_relevant_sale(today: date, pub_pattern: Optional[dict]) -> Optional[dict]:
    """Find the next upcoming sale that's relevant for this publisher."""
    preferred = pub_pattern["preferred_sales"] if pub_pattern else ["summer", "winter"]

    upcoming = [
        e for e in STEAM_SALE_EVENTS
        if datetime.strptime(e["start"], "%Y-%m-%d").date() > today
    ]
    upcoming.sort(key=lambda e: e["start"])

    # First try preferred sales
    for event in upcoming:
        key = event["key"].lower()
        if any(pref in key for pref in preferred):
            return event

    # Fallback: next any sale
    return upcoming[0] if upcoming else None


def _event_name(key: str) -> str:
    for fragment, name in SALE_FRIENDLY.items():
        if fragment in key.lower():
            return name
    return key.replace("_", " ").title()


def _guess_discount(game: Game) -> int:
    """Estimate discount based on historical low if available."""
    if game.price and game.price_history and game.price_history.all_time_low > 0:
        low  = game.price_history.all_time_low
        base = game.price.base
        if base > 0:
            return min(90, int((1 - low / base) * 100))
    return 40  # generic fallback


def _est_price(base: float, pub_pattern: Optional[dict]) -> Optional[float]:
    if not base:
        return None
    disc = pub_pattern["max_discount"] if pub_pattern else 40
    return round(base * (1 - disc / 100), 2)
