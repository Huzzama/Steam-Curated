"""
Deal predictor — Steam Curator's own "buy now or wait?" algorithm.

Input: the game's deal history (dates + discount %, see services.deal_history),
its current price in the user's currency, its publisher and the Steam sale
calendar. Output: statistics about past deals and a prediction of the next
one, with the estimated price computed from the base price in the user's
currency.

How it works
  1. Price-change events → sale *episodes* (start, end, deepest cut).
  2. Statistics over the last 3 years: how many sales, deepest cut ever,
     typical cut (median of the last 24 months), average gap between sales,
     days since the last one.
  3. Seasonal behaviour: for every big Steam sale window (spring, summer,
     Halloween, autumn/Black Friday, winter, Lunar New Year) the fraction of
     past years the game joined it, and its typical cut in that sale.
  4. Next sale: the upcoming calendar events are scored with that
     participation rate (or a prior from the publisher's habits when there
     is no history); frequent discounters also get a gap-based estimate.
  5. Verdict: buy now (at / near its record discount), good deal (at or
     above its usual discount), wait (a better, likely sale is coming) or
     fair price (a game that is almost never discounted).
Confidence grows with the number of past sales and the probability of the
predicted one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Iterable, Optional

# ── seasons ──────────────────────────────────────────────────────────────────

# (month, day) start → (month, day) end; windows are a little wider than the
# real sales so a game that starts its deal a day early still counts.
SEASONS: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
    "lunar":     ((1, 18), (2, 14)),
    "spring":    ((3, 8), (3, 27)),
    "summer":    ((6, 18), (7, 14)),
    "halloween": ((10, 22), (11, 4)),
    "autumn":    ((11, 18), (12, 6)),     # Autumn sale + Black Friday
    "winter":    ((12, 15), (1, 8)),      # crosses the new year
}
# chance a game joins a season when we know nothing about it
SEASON_PRIOR = {"summer": 0.6, "winter": 0.6, "autumn": 0.5, "spring": 0.45, "halloween": 0.3, "lunar": 0.35}

PUBLISHER_PATTERNS: dict[str, dict] = {
    # publisher fragment → deepest usual cut and the sales it prefers
    "bandai namco": {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "capcom":       {"max_discount": 80, "preferred_sales": ["summer", "winter", "spring"]},
    "square enix":  {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "atlus":        {"max_discount": 50, "preferred_sales": ["summer", "winter"]},
    "sega":         {"max_discount": 75, "preferred_sales": ["summer", "winter", "spring"]},
    "bethesda":     {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "ubisoft":      {"max_discount": 85, "preferred_sales": ["summer", "winter", "autumn"]},
    "electronic arts": {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "2k":           {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "activision":   {"max_discount": 67, "preferred_sales": ["summer", "winter"]},
    "konami":       {"max_discount": 70, "preferred_sales": ["summer", "winter"]},
    "warner":       {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "505 games":    {"max_discount": 75, "preferred_sales": ["summer", "winter", "spring"]},
    "devolver":     {"max_discount": 90, "preferred_sales": ["summer", "winter", "spring"]},
    "paradox":      {"max_discount": 75, "preferred_sales": ["summer", "winter", "spring"]},
    "annapurna":    {"max_discount": 70, "preferred_sales": ["summer", "winter", "spring"]},
    "focus":        {"max_discount": 75, "preferred_sales": ["summer", "winter", "autumn"]},
    "thq nordic":   {"max_discount": 80, "preferred_sales": ["summer", "winter", "spring"]},
    "team17":       {"max_discount": 75, "preferred_sales": ["summer", "winter", "spring"]},
    "cd projekt":   {"max_discount": 65, "preferred_sales": ["summer", "winter", "autumn"]},
    "sony":         {"max_discount": 50, "preferred_sales": ["summer", "winter"]},
    "playstation":  {"max_discount": 50, "preferred_sales": ["summer", "winter"]},
    "nintendo":     {"max_discount": 0,  "preferred_sales": []},
}

_HISTORY_DAYS = 3 * 365
_TYPICAL_DAYS = 2 * 365
_OPEN_EPISODE_DAYS = 21       # an observed sale with no "back to full price" event ends after this


def season_of(key: str) -> Optional[str]:
    """Calendar event key → season name ("summer_sale_2026" → "summer")."""
    k = (key or "").lower()
    if "black_friday" in k or "autumn" in k or "autum" in k:
        return "autumn"
    for s in ("summer", "winter", "spring", "halloween", "lunar"):
        if s in k:
            return s
    return None


def _d(iso: str) -> date:
    return date.fromisoformat(iso[:10])


def _in_window(day: date, season: str, year: int) -> bool:
    (m1, d1), (m2, d2) = SEASONS[season]
    start = date(year, m1, d1)
    end = date(year + (1 if (m2, d2) < (m1, d1) else 0), m2, d2)
    return start <= day <= end


def _window(season: str, year: int) -> tuple[date, date]:
    (m1, d1), (m2, d2) = SEASONS[season]
    start = date(year, m1, d1)
    return start, date(year + (1 if (m2, d2) < (m1, d1) else 0), m2, d2)


def match_publisher(publisher: str) -> Optional[dict]:
    p = (publisher or "").lower()
    for frag, data in PUBLISHER_PATTERNS.items():
        if frag in p:
            return data
    return None


# ── data ─────────────────────────────────────────────────────────────────────

@dataclass
class Episode:
    start: date
    end: Optional[date]
    cut: int

    def overlaps(self, a: date, b: date) -> bool:
        e = self.end or self.start
        return self.start <= b and e >= a


@dataclass
class Stats:
    episodes: list[Episode] = field(default_factory=list)
    coverage_from: Optional[date] = None
    times: int = 0
    max_cut: int = 0
    max_cut_date: Optional[date] = None
    typical_cut: int = 0
    last: Optional[Episode] = None
    avg_gap_days: Optional[int] = None
    season_rate: dict[str, float] = field(default_factory=dict)
    season_cut: dict[str, int] = field(default_factory=dict)
    source: str = "none"              # itad · seen · none

    @property
    def coverage_days(self) -> int:
        return (date.today() - self.coverage_from).days if self.coverage_from else 0


@dataclass
class Prediction:
    when: date
    cut: int
    prob: float
    event_key: Optional[str] = None     # calendar key, or None for a gap-based guess
    season: Optional[str] = None
    kind: str = "event"                 # event · gap · prior


# ── 1+2+3: statistics ────────────────────────────────────────────────────────

def episodes_from(events: Iterable[tuple], today: Optional[date] = None) -> list[Episode]:
    """Price-change events (iso, cut, src) → sale episodes."""
    today = today or date.today()
    out: list[Episode] = []
    cur: Optional[Episode] = None
    last_day: Optional[date] = None
    for iso, cut, _src in sorted(events, key=lambda e: e[0]):
        day = _d(iso)
        cut = int(cut or 0)
        if cur is not None and last_day is not None and (day - last_day).days > _OPEN_EPISODE_DAYS and cut > 0:
            cur.end = last_day + timedelta(days=1)       # observations are sparse: close stale episode
            out.append(cur)
            cur = None
        if cut > 0:
            if cur is None:
                cur = Episode(day, None, cut)
            else:
                cur.cut = max(cur.cut, cut)
        elif cur is not None:
            cur.end = day
            out.append(cur)
            cur = None
        last_day = day
    if cur is not None:
        if last_day and (today - last_day).days > _OPEN_EPISODE_DAYS:
            cur.end = last_day + timedelta(days=1)
        out.append(cur)
    return out


def compute_stats(events: list[tuple], coverage_from: Optional[str] = None,
                  today: Optional[date] = None) -> Stats:
    today = today or date.today()
    horizon = today - timedelta(days=_HISTORY_DAYS)
    eps = [e for e in episodes_from(events, today) if (e.end or e.start) >= horizon]
    st = Stats(episodes=eps)
    srcs = {e[2] for e in events}
    st.source = "itad" if "itad" in srcs else ("seen" if srcs else "none")
    cov = _d(coverage_from) if coverage_from else (_d(min(e[0] for e in events)) if events else None)
    st.coverage_from = max(cov, horizon) if cov else None
    if not eps:
        return st
    st.times = len(eps)
    best = max(eps, key=lambda e: (e.cut, e.start))
    st.max_cut, st.max_cut_date = best.cut, best.start
    recent = [e.cut for e in eps if e.start >= today - timedelta(days=_TYPICAL_DAYS)] or [e.cut for e in eps]
    st.typical_cut = int(round(median(recent)))
    st.last = max(eps, key=lambda e: e.start)
    if len(eps) >= 2:
        starts = sorted(e.start for e in eps)
        gaps = [(b - a).days for a, b in zip(starts, starts[1:]) if (b - a).days > 0]
        st.avg_gap_days = int(round(sum(gaps) / len(gaps))) if gaps else None

    # seasonal participation over fully covered windows
    if st.coverage_from:
        for season in SEASONS:
            seen = joined = 0
            cuts: list[int] = []
            for year in range(st.coverage_from.year - 1, today.year + 1):
                a, b = _window(season, year)
                if a < st.coverage_from or b >= today:
                    continue
                seen += 1
                hits = [e for e in eps if e.overlaps(a, b)]
                if hits:
                    joined += 1
                    cuts.append(max(h.cut for h in hits))
            if seen:
                # Laplace smoothing: 3 of 3 summers → 80 %, not a cocky 100 %
                st.season_rate[season] = round((joined + 1) / (seen + 2), 2)
                if cuts:
                    st.season_cut[season] = int(round(median(cuts)))
    return st


# ── 4: next sale ─────────────────────────────────────────────────────────────

def _upcoming_events(today: date) -> list[dict]:
    try:
        from services.sale_images import get_sale_events
        evs = get_sale_events()
    except Exception:  # noqa: BLE001
        evs = []
    if not evs:
        from config import STEAM_SALE_EVENTS
        evs = STEAM_SALE_EVENTS
    out = []
    for e in evs:
        try:
            start = _d(e["start"])
        except (KeyError, ValueError):
            continue
        if today < start <= today + timedelta(days=240) and season_of(e.get("key", "")):
            out.append(dict(e, _start=start))
    out.sort(key=lambda e: e["_start"])
    return out


def _calendar_guess(today: date) -> list[dict]:
    """Next occurrence of every season when the server calendar is empty."""
    out = []
    for season, ((m, d), _end) in SEASONS.items():
        for y in (today.year, today.year + 1):
            s = date(y, m, d) + timedelta(days=4)
            if s > today:
                out.append({"key": f"{season}_sale_{y}", "_start": s})
                break
    return sorted(out, key=lambda e: e["_start"])


def predict_next(st: Stats, publisher: str = "", on_sale_now: bool = False,
                 today: Optional[date] = None, calendar: Optional[list[dict]] = None) -> Optional[Prediction]:
    today = today or date.today()
    pub = match_publisher(publisher)
    if pub is not None and pub["max_discount"] == 0 and st.times == 0:
        return None                                     # publisher never discounts
    cal = calendar if calendar is not None else (_upcoming_events(today) or _calendar_guess(today))
    never = st.times == 0 and st.coverage_days >= 365

    fallback_cut = st.typical_cut or (int(pub["max_discount"] * 0.8) if pub else 40)
    candidates: list[Prediction] = []
    for ev in cal:
        season = season_of(ev.get("key", ""))
        if not season:
            continue
        if season in st.season_rate:
            prob = st.season_rate[season]
            kind = "event"
        else:
            prob = SEASON_PRIOR.get(season, 0.3)
            if pub and season in pub["preferred_sales"]:
                prob = min(0.85, prob + 0.15)
            if st.times >= 3:                           # discounts regularly, just not seen in this season
                prob = min(0.85, prob + 0.1)
            kind = "prior"
        if never:
            prob *= 0.3
        cut = st.season_cut.get(season) or fallback_cut
        if st.max_cut:
            cut = min(cut, max(st.max_cut, st.typical_cut))
        if on_sale_now and (ev["_start"] - today).days < 10:
            continue                                    # the current deal usually is this event
        candidates.append(Prediction(ev["_start"], int(cut), round(prob, 2), ev.get("key"), season, kind))

    # frequent discounters: next deal ≈ last one + usual gap
    if st.last and st.avg_gap_days and st.avg_gap_days <= 75 and st.times >= 4:
        nxt = st.last.start + timedelta(days=st.avg_gap_days)
        while nxt <= today:
            nxt += timedelta(days=st.avg_gap_days)
        if not on_sale_now or (nxt - today).days >= 10:
            candidates.append(Prediction(nxt, st.typical_cut, 0.6, None, None, "gap"))

    if not candidates:
        return None
    likely = [c for c in candidates if c.prob >= 0.5]
    if likely:
        return min(likely, key=lambda c: c.when)
    return max(candidates, key=lambda c: (c.prob * c.cut, -c.when.toordinal()))


# ── 5: verdict ───────────────────────────────────────────────────────────────

def confidence(st: Stats, prob: Optional[float] = None) -> str:
    score = 0 if st.times == 0 else 1 if st.times <= 2 else 2 if st.times <= 5 else 3
    if st.source == "itad":
        score += 1
    if prob is not None:
        score += 1 if prob >= 0.75 else (-1 if prob < 0.5 else 0)
    return "high" if score >= 4 else "medium" if score >= 2 else "low"


@dataclass
class Verdict:
    verdict: str                        # buy_now · good_deal · wait · fair · no_data
    reason_key: str                     # i18n key suffix under recommendation.*
    confidence: str
    stats: Stats
    prediction: Optional[Prediction]
    current_cut: int
    typical_used: int                   # the "usual" discount the verdict compared against


def decide(st: Stats, current_cut: int, publisher: str = "", today: Optional[date] = None,
           calendar: Optional[list[dict]] = None) -> Verdict:
    today = today or date.today()
    pub = match_publisher(publisher)
    on_sale = current_cut > 0
    pred = predict_next(st, publisher, on_sale, today, calendar)
    typical = st.typical_cut or (int(pub["max_discount"] * 0.8) if pub and pub["max_discount"] else 50)

    def v(kind, key, prob=None, typ=typical):
        return Verdict(kind, key, confidence(st, prob), st, pred, current_cut, typ)

    if on_sale:
        if st.max_cut and current_cut >= st.max_cut - 3:
            return v("buy_now", "record")
        if st.times and current_cut >= typical:
            if pred and pred.cut >= current_cut + 15 and pred.prob >= 0.6 and (pred.when - today).days <= 45:
                return v("good_deal", "good_but_better_soon", pred.prob)
            return v("good_deal", "at_usual")
        if not st.times and current_cut >= typical - 10:
            return v("good_deal", "good_no_history", 0.5)
        if pred and pred.cut >= current_cut + 10 and pred.prob >= 0.5 and (pred.when - today).days <= 75:
            return v("wait", "small_discount_better_soon", pred.prob)
        return v("good_deal", "modest", 0.4)

    if pub is not None and pub["max_discount"] == 0 and st.times == 0:
        return v("fair", "never_discounts_publisher")
    if st.times == 0 and st.coverage_days >= 365:
        return v("fair", "never_discounted")
    if pred:
        return v("wait", "wait_event" if pred.kind != "gap" else "wait_gap", pred.prob)
    if st.times:
        return v("wait", "wait_generic", 0.4)
    return v("no_data", "no_data")
