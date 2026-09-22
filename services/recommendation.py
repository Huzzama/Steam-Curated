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


def _t(key: str, **kw) -> str:
    import i18n
    return i18n.t(f"recommendation.{key}", **kw)


def _m(amount: float, currency: str) -> str:
    from ui.format import money
    return money(amount, currency)


def get_recommendation(game: Game) -> dict:
    """
    Returns a structured, already-localised recommendation:
    {
        "verdict":       "wait" | "buy_now" | "good_deal" | "no_data",
        "headline":      str,          # short one-liner (localised)
        "reason":        str,          # explanation (localised)
        "next_sale":     str | None,   # "Summer Sale 2026 · 25 Jun"
        "next_sale_date":str | None,   # ISO date
        "est_discount":  int | None,   # estimated % during that sale
        "est_price":     float | None, # estimated sale price
        "confidence":    "high" | "medium" | "low",
    }
    """
    price   = game.price
    history = game.price_history

    if not price:
        return _no_data()

    today       = date.today()
    diff_pct    = game.price_diff_pct    # % above historical low (None if no history)
    pub_pattern = _match_publisher((game.publisher or "").lower())
    cur         = price.currency
    now_str     = _m(price.current, cur)
    low_str     = _m(history.all_time_low, cur) if history else ""

    observed_note = ""
    if history is not None and getattr(history, "source", "") == "observed":
        observed_note = " " + _t("why_observed", date=history.all_time_low_date or "")

    # ── No history at all: judge the current discount against what this
    #    publisher (or Steam in general) typically bottoms out at ─────────────
    if history is None and price.is_on_sale and price.discount_pct:
        typical = pub_pattern["max_discount"] if pub_pattern else 50
        if price.discount_pct >= typical - 10:
            return {
                "verdict":        "good_deal",
                "headline":       _t("hl_good_deal", pct=price.discount_pct),
                "reason":         _t("why_estimate_sale", now=now_str, pct=price.discount_pct,
                                     typical=typical,
                                     est=_m(round(price.base * (1 - typical / 100), 2), cur)),
                "next_sale":      None,
                "next_sale_date": None,
                "est_discount":   price.discount_pct,
                "est_price":      price.current,
                "confidence":     "medium" if pub_pattern else "low",
            }

    # ── Already at or near historical low ────────────────────────────────────
    if diff_pct is not None and diff_pct <= 5:
        return {
            "verdict":        "buy_now",
            "headline":       _t("hl_buy_now"),
            "reason":         _t("why_buy_now", now=now_str, low=low_str) + observed_note,
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
            "headline":       _t("hl_good_deal", pct=price.discount_pct),
            "reason":         _t("why_good_deal", now=now_str, low=low_str,
                                 more=_m(max(0.0, price.current - history.all_time_low), cur)) + observed_note,
            "next_sale":      None,
            "next_sale_date": None,
            "est_discount":   price.discount_pct,
            "est_price":      price.current,
            "confidence":     "high",
        }

    # ── Find next likely sale ─────────────────────────────────────────────────
    next_event = _next_relevant_sale(today, pub_pattern)

    if next_event is None:
        if diff_pct is not None and diff_pct > 30:
            return {
                "verdict":        "wait",
                "headline":       _t("hl_wait"),
                "reason":         _t("why_above_low", now=now_str, pct=round(diff_pct), low=low_str) + observed_note,
                "next_sale":      None,
                "next_sale_date": None,
                "est_discount":   pub_pattern["max_discount"] if pub_pattern else None,
                "est_price":      _est_price(price.base, pub_pattern),
                "confidence":     "low",
            }
        return _no_data()

    est_discount = pub_pattern["max_discount"] if pub_pattern else _guess_discount(game)
    est_price    = round(price.base * (1 - est_discount / 100), 2)
    start_date   = datetime.strptime(next_event["start"], "%Y-%m-%d").date()
    days_away    = (start_date - today).days
    event_name   = _event_name(next_event["key"])

    from ui.format import day
    sale_label = f"{event_name} · {day(start_date, '{d} {mon}')}"

    parts = [_t("why_above_low", now=now_str, pct=round(diff_pct), low=low_str) + observed_note.strip()
             if diff_pct is not None else _t("why_current", now=now_str)]
    if pub_pattern:
        parts.append(_t("why_publisher", publisher=game.publisher, pct=pub_pattern["max_discount"]))
    parts.append(_t("why_next_sale_one" if days_away == 1 else "why_next_sale_other",
                    event=event_name, days=days_away, price=_m(est_price, cur)))

    return {
        "verdict":        "wait",
        "headline":       _t("hl_wait_days_one" if days_away == 1 else "hl_wait_days_other", days=days_away),
        "reason":         " ".join(parts),
        "next_sale":      sale_label,
        "next_sale_date": next_event["start"],
        "est_discount":   est_discount,
        "est_price":      est_price,
        "confidence":     "high" if pub_pattern else "medium",
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _no_data() -> dict:
    return {
        "verdict": "no_data", "headline": _t("hl_no_data"),
        "reason": _t("why_no_data_refresh"),
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

    # Same event list the Deals screen uses (server JSON, config as fallback)
    try:
        from services.sale_images import get_sale_events
        events = get_sale_events() or STEAM_SALE_EVENTS
    except Exception:  # noqa: BLE001
        events = STEAM_SALE_EVENTS
    upcoming = [
        e for e in events
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
    import i18n
    name = i18n.t(f"sale_events.{key}")
    if name != f"sale_events.{key}":
        return name
    for fragment, friendly in SALE_FRIENDLY.items():
        if fragment in key.lower():
            return friendly
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
