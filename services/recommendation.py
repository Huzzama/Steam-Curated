"""
"Buy now or wait?" — turns services.deal_predictor's verdict into the
localised dict the UI shows. All prices are in the game's own currency.

get_recommendation(game) → {
    "verdict":        "buy_now" | "good_deal" | "wait" | "fair" | "no_data",
    "headline", "reason":   localised strings,
    "next_sale":      "Summer Sale 2027 · 25 Jun" | None,
    "next_sale_date": ISO date | None,
    "est_discount":   int | None,      "est_price": float | None,
    "probability":    0..1 | None,
    "confidence":     "high" | "medium" | "low",
    "stats":   {"times", "max_cut", "max_cut_date", "typical_cut", "last_start",
                "last_cut", "avg_gap_days", "years", "source"},
    "episodes": [{"start", "end", "cut", "price"}, …]   newest first, max 12
}
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from data.models import Game
from services.deal_predictor import PUBLISHER_PATTERNS, match_publisher  # noqa: F401  (re-export)

SALE_FRIENDLY: dict[str, str] = {
    "summer": "Summer Sale", "winter": "Winter Sale", "spring": "Spring Sale", "autumn": "Autumn Sale",
    "halloween": "Halloween Sale", "black_friday": "Black Friday", "lunar": "Lunar New Year Sale",
}


def _t(key: str, **kw) -> str:
    import i18n
    return i18n.t(f"recommendation.{key}", **kw)


def _m(amount: Optional[float], currency: str) -> str:
    from ui.format import money
    return money(amount, currency)


def _day(d: Optional[date]) -> str:
    from ui.format import day
    return day(d) if d else "—"


def _event_name(key: str) -> str:
    import i18n
    name = i18n.t(f"sale_events.{key}")
    if name != f"sale_events.{key}":
        return name
    for fragment, friendly in SALE_FRIENDLY.items():
        if fragment in (key or "").lower():
            return friendly
    return (key or "").replace("_", " ").title()


def get_recommendation(game: Game, today: Optional[date] = None,
                       calendar: Optional[list[dict]] = None) -> dict:
    from services import deal_history
    from services.deal_predictor import compute_stats, decide

    price = game.price
    if price is None:
        return _no_data()
    today = today or date.today()
    app_id = str(game.app_id or "")
    evs = deal_history.events(app_id) if app_id else []
    st = compute_stats(evs, deal_history.coverage_start(app_id) if app_id else None, today)
    cur_cut = int(price.discount_pct or 0) if price.is_on_sale else 0
    v = decide(st, cur_cut, game.publisher or "", today, calendar)
    pred = v.prediction

    cur = price.currency
    base = price.base or price.current
    at = lambda cut: round(base * (1 - cut / 100), 2)  # noqa: E731
    now_s = _m(price.current, cur)
    years = max(1, round(st.coverage_days / 365)) if st.coverage_days else 3
    pred_name = (_event_name(pred.event_key) if pred and pred.event_key else _t("next_regular_deal"))
    pred_days = (pred.when - today).days if pred else None
    kw = dict(
        now=now_s, cut=cur_cut, max=st.max_cut, typical=v.typical_used, years=years,
        date=_day(st.max_cut_date), times=st.times, gap=st.avg_gap_days or 0,
        lcut=st.last.cut if st.last else 0, ldate=_day(st.last.start if st.last else None),
        publisher=game.publisher or "",
        event=pred_name, days=pred_days or 0, pcut=pred.cut if pred else 0,
        price=_m(at(pred.cut), cur) if pred else "—", prob=int(round((pred.prob if pred else 0) * 100)),
    )

    r = v.reason_key
    if v.verdict == "no_data":
        return _no_data(st)
    if r == "record":
        headline, reason = _t("hl_record"), _t("why_record", **kw)
    elif r == "at_usual":
        headline, reason = _t("hl_good_deal", pct=cur_cut), _t("why_at_usual", **kw)
    elif r == "good_but_better_soon":
        headline, reason = _t("hl_good_better_soon"), _t("why_good_better_soon", **kw)
    elif r == "good_no_history":
        headline, reason = _t("hl_good_deal", pct=cur_cut), _t("why_good_no_history", **kw)
    elif r == "small_discount_better_soon":
        headline, reason = _t("hl_wait_bigger"), _t("why_small_better_soon", **kw)
    elif r == "modest":
        headline, reason = _t("hl_modest", pct=cur_cut), _t("why_modest", **kw)
    elif r == "never_discounts_publisher":
        headline, reason = _t("hl_fair_publisher"), _t("why_fair_publisher", **kw)
    elif r == "never_discounted":
        headline, reason = _t("hl_fair"), _t("why_fair", **kw)
    elif r in ("wait_event", "wait_gap"):
        headline = _t("hl_wait_days_one" if pred_days == 1 else "hl_wait_days_other", days=pred_days)
        if r == "wait_gap":
            reason = _t("why_wait_gap", **kw)
        elif pred and pred.kind == "event":
            reason = _t("why_wait_event_history", **kw)
        else:
            reason = _t("why_wait_event_prior", **kw)
    else:                                           # wait_generic
        headline, reason = _t("hl_wait"), _t("why_wait_generic", **kw)

    out = {
        "verdict":        v.verdict,
        "headline":       headline,
        "reason":         reason,
        "next_sale":      f"{pred_name} · {_day(pred.when)}" if pred and v.verdict in ("wait", "good_deal") else None,
        "next_sale_date": pred.when.isoformat() if pred else None,
        "est_discount":   pred.cut if pred else None,
        "est_price":      at(pred.cut) if pred else None,
        "probability":    pred.prob if pred else None,
        "confidence":     v.confidence,
    }
    out.update(_stats_dict(st, base))
    return out


def _stats_dict(st, base: Optional[float]) -> dict:
    eps = sorted(st.episodes, key=lambda e: e.start, reverse=True)[:12]
    return {
        "stats": {
            "times": st.times, "max_cut": st.max_cut,
            "max_cut_date": st.max_cut_date.isoformat() if st.max_cut_date else None,
            "typical_cut": st.typical_cut,
            "last_start": st.last.start.isoformat() if st.last else None,
            "last_cut": st.last.cut if st.last else None,
            "avg_gap_days": st.avg_gap_days,
            "years": max(1, round(st.coverage_days / 365)) if st.coverage_days else 0,
            "source": st.source,
        },
        "episodes": [{"start": e.start.isoformat(), "end": e.end.isoformat() if e.end else None,
                      "cut": e.cut, "price": round(base * (1 - e.cut / 100), 2) if base else None}
                     for e in eps],
    }


def _no_data(st=None) -> dict:
    out = {
        "verdict": "no_data", "headline": _t("hl_no_data"),
        "reason": _t("why_no_data_refresh"),
        "next_sale": None, "next_sale_date": None, "probability": None,
        "est_discount": None, "est_price": None, "confidence": "low",
    }
    if st is not None:
        out.update(_stats_dict(st, None))
    return out
