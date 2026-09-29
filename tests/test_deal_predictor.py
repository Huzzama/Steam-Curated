"""The buy-now-or-wait algorithm on realistic, hand-built histories."""
from datetime import date

from services.deal_predictor import compute_stats, decide, episodes_from, predict_next, season_of

TODAY = date(2026, 5, 20)
CAL = [{"key": "summer_sale_2026", "start": "2026-06-25", "end": "2026-07-09"},
       {"key": "halloween_sale_2026", "start": "2026-10-27", "end": "2026-10-31"},
       {"key": "autumn_sale_2026", "start": "2026-11-25", "end": "2026-12-02"}]
for e in CAL:
    e["_start"] = date.fromisoformat(e["start"])


def seasonal_game():
    """-40% every summer & winter for 3 years, -50% last winter."""
    evs = []
    for y in (2023, 2024, 2025):
        evs += [(f"{y}-06-27", 40, "itad"), (f"{y}-07-11", 0, "itad")]
        evs += [(f"{y}-12-19", 50 if y == 2025 else 40, "itad"), (f"{y + 1}-01-02", 0, "itad")]
    return evs


def test_episodes_group_changes():
    eps = episodes_from([("2025-06-26", 30, "itad"), ("2025-06-30", 40, "itad"), ("2025-07-10", 0, "itad")], TODAY)
    assert len(eps) == 1 and eps[0].cut == 40 and eps[0].end == date(2025, 7, 10)


def test_sparse_observations_close_after_three_weeks():
    eps = episodes_from([("2025-01-01", 20, "seen"), ("2025-03-01", 20, "seen")], TODAY)
    assert len(eps) == 2


def test_stats_and_seasons():
    st = compute_stats(seasonal_game(), "2023-05-20", TODAY)
    assert st.times == 6 and st.max_cut == 50 and st.typical_cut == 40
    assert st.season_rate["summer"] == 0.8 and st.season_rate["winter"] == 0.8   # 3/3, smoothed
    assert st.season_rate["halloween"] == 0.2                                    # 0/3, smoothed
    assert st.source == "itad"


def test_full_price_waits_for_summer():
    st = compute_stats(seasonal_game(), "2023-05-20", TODAY)
    v = decide(st, 0, "", TODAY, CAL)
    assert v.verdict == "wait" and v.prediction.season == "summer"
    assert v.prediction.cut == 40 and v.prediction.prob == 0.8
    assert v.confidence == "high"


def test_record_discount_is_buy_now():
    st = compute_stats(seasonal_game(), "2023-05-20", TODAY)
    assert decide(st, 50, "", TODAY, CAL).verdict == "buy_now"


def test_usual_discount_is_good_deal():
    st = compute_stats(seasonal_game(), "2023-05-20", TODAY)
    v = decide(st, 40, "", TODAY, CAL)
    assert v.verdict == "good_deal"


def test_small_discount_before_big_sale_waits():
    st = compute_stats(seasonal_game(), "2023-05-20", TODAY)
    v = decide(st, 10, "", TODAY, CAL)
    assert v.verdict == "wait" and v.reason_key == "small_discount_better_soon"


def test_never_discounted_is_fair():
    st = compute_stats([("2023-05-20", 0, "itad")], "2023-05-20", TODAY)
    assert decide(st, 0, "", TODAY, CAL).verdict == "fair"


def test_nintendo_is_fair_without_history():
    st = compute_stats([], None, TODAY)
    assert decide(st, 0, "Nintendo", TODAY, CAL).verdict == "fair"


def test_no_history_uses_publisher_prior():
    st = compute_stats([], None, TODAY)
    v = decide(st, 0, "Capcom", TODAY, CAL)
    assert v.verdict == "wait" and v.prediction.kind == "prior"
    assert v.prediction.cut == 64          # 80% max * 0.8
    assert v.confidence == "low"


def test_frequent_discounter_gap_prediction():
    evs = []
    for m in range(1, 13):                  # a deal every month in 2025–26
        evs += [(f"2025-{m:02d}-01", 30, "itad"), (f"2025-{m:02d}-08", 0, "itad")]
    evs += [("2026-04-20", 30, "itad"), ("2026-04-27", 0, "itad")]
    st = compute_stats(evs, "2023-05-20", TODAY)
    p = predict_next(st, "", False, TODAY, [])
    assert p is not None and p.kind == "gap" and (p.when - TODAY).days <= 40


def test_season_of_keys():
    assert season_of("black_friday_2026") == "autumn"
    assert season_of("summer_sale_2027") == "summer"
    assert season_of("BANNER_FEATURED") is None
