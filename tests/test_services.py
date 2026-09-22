import json

import pytest

import i18n
from data.models import PriceHistory
from services.steam_wishlist import map_steam_priority
from services import recommendation, steamkustom_auth as acct


def test_priority_mapping():
    assert map_steam_priority(0) == "B"
    assert map_steam_priority(1) == "S"
    assert map_steam_priority(3) == "S"
    assert map_steam_priority(10) == "A"
    assert map_steam_priority(25) == "B"
    assert map_steam_priority(26) == "C"


def test_recommendation_is_localised():
    from tests.conftest import sample_games
    i18n.load_locale("en")
    rec = recommendation.get_recommendation(sample_games()[0])
    assert rec["verdict"] in ("wait", "good_deal", "buy_now")
    assert "$35.99" in rec["reason"]
    assert "recommendation." not in rec["headline"]
    i18n.load_locale("es")
    rec_es = recommendation.get_recommendation(sample_games()[0])
    assert rec_es["headline"] != rec["headline"]
    i18n.load_locale("en")


def test_recommendation_no_price():
    from tests.conftest import sample_games
    g = sample_games()[1]
    g.price = None
    assert recommendation.get_recommendation(g)["verdict"] == "no_data"


def test_creds_roundtrip(data_dir):
    acct._creds_cache = None
    acct.clear_token()
    assert not acct.is_connected()
    acct.save_account("tok123", {"steam_id64": "7656119", "username": "ryu"})
    assert acct.get_token() == "tok123"
    assert acct.get_steam_id() == "7656119"
    assert acct.get_username() == "ryu"
    assert json.loads((data_dir / "creds.json").read_text())["app_token"] == "tok123"
    acct.clear_token()
    assert not acct.is_connected()


def test_price_history_without_key(data_dir):
    from services import price_history
    assert not price_history.is_configured()
    assert price_history.get_price_history("1245620", "US") is None


def test_wishlist_shapes_are_normalised(monkeypatch):
    from services import steamkustom_auth as acct
    shapes = [
        {"response": {"items": [{"appid": 10, "priority": 2, "date_added": 5}]}},
        {"items": [{"appid": "10", "priority": "2"}]},
        [{"app_id": 10}],
        {"10": {"name": "Ten", "priority": 2}},
    ]
    for shape in shapes:
        monkeypatch.setattr(acct, "api", lambda *a, **k: shape)
        items = acct.get_wishlist()
        assert items and items[0]["appid"] == "10", shape
        assert isinstance(items[0]["priority"], int)


def test_player_summary_shapes(monkeypatch):
    from services import steamkustom_auth as acct
    monkeypatch.setattr(acct, "api", lambda *a, **k: {"response": {"players": [{"personaname": "ryu", "steamid": "7"}]}})
    assert acct.get_player_summary()["name"] == "ryu"
    monkeypatch.setattr(acct, "api", lambda *a, **k: {"personaname": "ryu2", "avatar_url": "x"})
    assert acct.get_player_summary()["avatar_url"] == "x"


def test_library_parses_community_xml(monkeypatch):
    from services import library_api

    class R:
        content = b"""<gamesList><steamID64>7</steamID64><games>
        <game><appID>10</appID><name>Counter-Strike</name><hoursLast2Weeks>1.5</hoursLast2Weeks><hoursOnRecord>1,234.5</hoursOnRecord></game>
        <game><appID>20</appID><name>TFC</name></game></games></gamesList>"""
        def raise_for_status(self): pass

    library_api.invalidate_cache()
    monkeypatch.setattr(library_api._SESSION, "get", lambda *a, **k: R())
    stats = library_api.get_library_stats("7")
    assert stats["total_games"] == 2
    assert stats["never_played_count"] == 1
    assert stats["most_played"]["hours"] == 1234.5
    assert stats["recently_played"][0]["hours_2w"] == 1.5


def test_observed_history_fallback(data_dir):
    from services import price_history as ph
    from data.models import PriceInfo
    ph._log_cache = None
    ph.observe("10", PriceInfo(20.0, 40.0, "USD", 50, True), when="2026-01-01")
    ph.observe("10", PriceInfo(30.0, 40.0, "USD", 25, True), when="2026-02-01")
    ph.observe("10", PriceInfo(15.0, 40.0, "USD", 62, True), when="2026-03-01")
    h = ph.get_price_history("10", "US")          # no ITAD key → observed tier
    assert h is not None and h.source == "observed"
    assert h.all_time_low == 15.0 and h.all_time_low_date == "2026-03-01"
    assert (data_dir / "price_log.json").exists()
    ph._log_cache = None                           # survives a reload
    assert ph.get_price_history("10", "US", currency="USD").all_time_low == 15.0
    assert ph.get_price_history("99", "US") is None


def test_history_merge_prefers_itad():
    from services import price_history as ph
    from data.models import PriceHistory
    itad = PriceHistory(9.0, "2025-01-01", 70, None, None, source="itad")
    obs = PriceHistory(5.0, "2026-01-01", 80, None, None, source="observed")
    assert ph.merge(itad, obs) is itad
    assert ph.merge(obs, itad) is itad
    assert ph.merge(None, obs) is obs
    obs2 = PriceHistory(7.0, "2026-02-01", 50, None, None, source="observed")
    assert ph.merge(obs, obs2) is obs        # keeps the lower observed low


def test_recommendation_without_history_uses_discount():
    from tests.conftest import sample_games
    i18n.load_locale("en")
    g = sample_games()[0]
    g.price_history = None                         # 40% off, Bandai Namco pattern (75%)
    rec = recommendation.get_recommendation(g)
    assert rec["verdict"] in ("good_deal", "wait")
    g.price.discount_pct = 70
    rec = recommendation.get_recommendation(g)
    assert rec["verdict"] == "good_deal" and rec["confidence"] == "medium"
