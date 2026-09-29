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


def test_price_history_is_local_only(data_dir):
    """No third-party API any more: an unknown game simply has no history."""
    from services import price_history
    assert not hasattr(price_history, "is_configured")
    assert price_history.get_price_history("1245620", "US") is None


def test_price_watch_records_sales(data_dir, monkeypatch):
    """The daily check refreshes wishlist prices, records deals, reports new sales."""
    import time
    import data.repository as repo
    from data.models import PriceInfo
    from services import deal_history, price_watch, steam_api
    from tests.conftest import sample_games
    repo.add_many(sample_games())
    assert price_watch.is_due()

    def fake_bulk(games, country="mx", on_progress=None, on_done=None, **_):
        assert all(g.status == "Wishlist" for g in games)         # purchased games skipped
        for i, g in enumerate(games, 1):
            g.price = PriceInfo(15.0, 29.99, "MXN", 50, True) if g.app_id == "1145350" else g.price
            if on_progress:
                on_progress(i, len(games), g.name)
        from services import price_history
        price_history.observe_many((g.app_id, g.price) for g in games)
        on_done(1, len(games) - 1, 0)

    monkeypatch.setattr(steam_api, "bulk_refresh_prices", fake_bulk)
    seen = []
    res = price_watch.check_now(lambda c, n: seen.append((c, n)))
    assert res["checked"] == 2 and res["new_sales"] == ["Hades II"]
    assert seen[-1] == (2, 2)
    assert not price_watch.is_due() and price_watch.last_check() <= time.time()
    assert deal_history.events("1145350")[-1][1] == 50
    assert deal_history.summary() == (2, 2)                  # Elden Ring (40 %) + Hades II (50 %)


def test_price_watch_offline_does_not_mark_done(data_dir, monkeypatch):
    import data.repository as repo
    from services import price_watch, steam_api
    from tests.conftest import sample_games
    repo.add_many(sample_games())
    monkeypatch.setattr(steam_api, "bulk_refresh_prices",
                        lambda games, on_done=None, **_: on_done(0, 0, len(games)))
    res = price_watch.check_now()
    assert res["checked"] == 0 and res["failed"] == 2
    assert price_watch.is_due()


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
    h = ph.get_price_history("10", "US")          # derived from what this app saw
    assert h is not None and h.source == "observed"
    assert h.all_time_low == 15.0 and h.all_time_low_date == "2026-03-01"
    assert (data_dir / "price_log.json").exists()
    ph._log_cache = None                           # survives a reload
    assert ph.get_price_history("10", "US", currency="USD").all_time_low == 15.0
    assert ph.get_price_history("99", "US") is None


def test_history_merge_drops_legacy_itad_lows():
    from services import price_history as ph
    from data.models import PriceHistory
    legacy = PriceHistory(9.0, "2025-01-01", 70, None, None, source="itad")      # old absolute USD low
    fresh = PriceHistory(150.0, "2025-06-26", 75, None, None, source="history")
    assert ph.merge(legacy, fresh) is fresh
    assert ph.merge(legacy, None) is None
    obs = PriceHistory(5.0, "2026-01-01", 80, None, None, source="observed")
    assert ph.merge(obs, None) is obs


def test_low_is_in_the_games_currency(data_dir):
    """A -75% record on a MX$999 game is MX$249.75 — never ITAD's USD amount."""
    from services import deal_history, price_history as ph
    from data.models import PriceInfo
    deal_history.reset_cache(); ph._log_cache = None
    deal_history.record("42", 75, "2025-06-26")
    deal_history.record("42", 0, "2025-07-10")
    h = ph.get_price_history("42", price=PriceInfo(999.0, 999.0, "MXN", 0, False))
    assert h.all_time_low == 249.75 and h.all_time_discount == 75 and h.all_time_low_date == "2025-06-26"


def test_recommendation_without_history_uses_discount(data_dir):
    from services import deal_history
    from tests.conftest import sample_games
    deal_history.reset_cache()
    i18n.load_locale("en")
    g = sample_games()[0]
    g.price_history = None                         # Bandai Namco, usual bottom ~-60%
    g.price.discount_pct = 70
    rec = recommendation.get_recommendation(g)
    assert rec["verdict"] == "good_deal"
    assert "$35.99" in rec["reason"]
    g.price.discount_pct, g.price.is_on_sale = 0, False
    rec = recommendation.get_recommendation(g)
    assert rec["verdict"] == "wait" and rec["est_price"] is not None


def test_recommendation_uses_history_and_currency(data_dir):
    from datetime import date
    from services import deal_history
    from data.models import PriceInfo
    from tests.conftest import sample_games
    deal_history.reset_cache()
    i18n.load_locale("en")
    for y in (2023, 2024, 2025):
        deal_history.record("1245620", 60, f"{y}-06-27"); deal_history.record("1245620", 0, f"{y}-07-11")
    g = sample_games()[0]
    g.price = PriceInfo(1199.0, 1199.0, "MXN", 0, False)
    cal = [{"key": "summer_sale_2026", "start": "2026-06-25", "_start": date(2026, 6, 25)}]
    rec = recommendation.get_recommendation(g, today=date(2026, 5, 20), calendar=cal)
    assert rec["verdict"] == "wait"
    assert rec["est_price"] == 479.6 and "MX$479.60" in rec["reason"]
    assert rec["stats"]["times"] == 3 and rec["stats"]["max_cut"] == 60
    assert rec["episodes"][0]["price"] == 479.6


def test_full_price_is_never_an_all_time_low(data_dir):
    """A game only ever seen at full price has no 'low' and is never 'at low'."""
    from services import price_history as ph
    from data.models import Game, PriceInfo, PriceHistory
    full = PriceInfo(459.99, 459.99, "MXN", 0, False)
    ph.observe("77", full, when="2026-09-28")
    assert ph.derive("77", full) is None
    stale = PriceHistory(459.99, "2026-09-28", 0, None, None, source="observed")
    assert ph.merge(stale, None) is None                      # old full-price lows are dropped
    g = Game(0, "AI LIMIT", "77", "", "", 2025, "", "", "", "", "B", "Wishlist", full, stale)
    assert not g.is_at_low
    sale = PriceInfo(275.99, 459.99, "MXN", 40, True)
    ph.observe("77", sale, when="2026-11-22")
    g.price, g.price_history = sale, ph.derive("77", sale)
    assert g.price_history.all_time_low == 275.99 and g.is_at_low
    g.price = full                                            # sale over → not at low any more
    assert not g.is_at_low


def test_fx_live_cached_and_builtin(data_dir, monkeypatch):
    from services import fx
    fx.reset_cache()

    class R:
        def raise_for_status(self): pass
        def json(self): return {"result": "success", "time_last_update_unix": 1790000000,
                                "rates": {"USD": 1, "MXN": 20.0, "ARS": 1000.0}}
    from services import _http
    calls = []
    monkeypatch.setattr(_http.SESSION, "get", lambda *a, **k: calls.append(1) or R())
    table, meta = fx.rates()
    assert meta["source"] == "live" and table["MXN"] == 20.0
    assert fx.convert(34.99, "USD", "MXN", table) == 34.99 * 20
    assert round(fx.convert(1000, "ARS", "MXN", table), 2) == 20.0
    fx.reset_cache()
    assert fx.rates()[1]["source"] == "cached" and len(calls) == 1   # 12 h cache on disk
    (data_dir / "fx_rates.json").unlink()
    fx.reset_cache()
    monkeypatch.setattr(_http.SESSION, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    table, meta = fx.rates()
    assert meta["source"] == "builtin" and fx.convert(1, "USD", "MXN", table) > 10


def test_library_xml_with_bad_characters_and_html():
    """One odd game name (control char / invalid UTF-8 / bare '&') must not break the
    whole library; a web page instead of XML gives a readable reason."""
    import pytest
    from services.library_api import LibraryError, parse_games_xml
    xml = (b'<?xml version="1.0"?><gamesList><games>\n'
           b'<game><appID>10</appID><name><![CDATA[Odd \x02 Name \xff]]></name><hoursOnRecord>2.5</hoursOnRecord></game>\n'
           b'<game><appID>20</appID><name>A & B</name></game></games></gamesList>')
    games = parse_games_xml(xml)
    assert [g["appid"] for g in games] == ["10", "20"]
    assert games[0]["playtime_forever"] == 150 and games[1]["name"] == "A & B"
    with pytest.raises(LibraryError, match="web page"):
        parse_games_xml(b"<!DOCTYPE html><html><body>Sign in</body></html>")
    with pytest.raises(LibraryError, match="private"):
        parse_games_xml(b'<?xml version="1.0"?><response><error><![CDATA[This profile is private.]]></error></response>')


def _purchase(**kw):
    from data.models import Purchase
    d = dict(app_id="10", name="Game A", purchased_at="2026-09-01", price_paid=100.0, base_price=400.0,
             currency="MXN", discount_pct=75, edition="Standard Edition", saved=300.0)
    d.update(kw)
    return Purchase(**d)


def test_purchase_sync_sends_and_stores_verification(data_dir, monkeypatch):
    from data import purchase_repository as prepo
    from services import purchase_sync, steamkustom_auth as acct
    sent = []

    def fake_api(path, method="GET", json_body=None, **_):
        sent.append((path, method, json_body))
        return {"verification": {"status": "partial", "items": [
            {"app_id": "10", "state": "owned"}, {"app_id": "20", "state": "missing"},
            {"app_id": "30", "state": "unverifiable"}]}}
    monkeypatch.setattr(acct, "get_token", lambda: "pmsa_x")
    monkeypatch.setattr(acct, "api", fake_api)
    p = _purchase(kind="bundle", items=[{"app_id": "20", "name": "B"}, {"app_id": "30", "name": "DLC"},
                                        {"app_id": "10", "name": "dup"}, {"app_id": "x", "name": "bad"}],
                  saving_reported=False)
    prepo.add(p)
    purchase_sync.send(p)
    path, method, body = sent[0]
    assert (path, method) == ("/purchases", "POST")
    assert body["kind"] == "bundle" and [i["app_id"] for i in body["items"]] == ["20", "30"]
    assert body["credit_saving"] is True and body["currency"] == "MXN"
    stored = prepo.get_by_app_id("10")
    assert stored.verification == "partial" and stored.saving_reported is True
    assert purchase_sync.summary(stored) == ("partial", "gold")


def test_purchase_backfill_and_old_backend(data_dir, monkeypatch):
    """Purchases from older versions are sent without crediting the saving again;
    a backend without /purchases falls back to the old savings report once."""
    import json
    from data import purchase_repository as prepo
    from services import purchase_sync, steamkustom_auth as acct
    from services._http import ApiError
    (data_dir / "purchases.json").write_text(json.dumps([
        {"app_id": "10", "name": "Old", "purchased_at": "2025-01-01", "price_paid": 5, "base_price": 20,
         "currency": "USD", "discount_pct": 75, "edition": "Standard", "saved": 15}]))
    prepo.invalidate()
    bodies = []
    monkeypatch.setattr(acct, "get_token", lambda: "pmsa_x")
    monkeypatch.setattr(acct, "api", lambda path, method="GET", json_body=None, **_:
                        bodies.append(json_body) or {"verification": {"status": "verified", "items": []}})
    assert purchase_sync.sync_pending() == {"sent": 1, "failed": 0, "skipped": 0}
    assert bodies[0]["credit_saving"] is False
    assert purchase_sync.sync_pending()["sent"] == 0                 # already verified

    reported = []
    prepo.add(_purchase(app_id="20", saving_reported=False))

    def old_backend(*_a, **_k):
        raise ApiError(404, "Not Found")
    monkeypatch.setattr(acct, "api", old_backend)
    monkeypatch.setattr(acct, "report_pending_saving", lambda amount, currency: reported.append((amount, currency)))
    res = purchase_sync.sync_pending()
    assert res["failed"] == 1 and reported == [(300.0, "MXN")]
    p = prepo.get_by_app_id("20")
    assert p.saving_reported and p.verification == ""                # retried later, never re-credited


def test_library_prefers_backend(monkeypatch):
    import pytest
    from services import library_api, steamkustom_auth as acct
    library_api.invalidate_cache()
    monkeypatch.setattr(acct, "get_token", lambda: "pmsa_x")
    monkeypatch.setattr(acct, "api", lambda path, **_: {"games": [
        {"appid": "10", "name": "A", "playtime_forever": 90, "playtime_2weeks": 30}], "private": False})
    monkeypatch.setattr(library_api._SESSION, "get", lambda *a, **k: pytest.fail("XML fallback used"))
    stats = library_api.get_library_stats("7")
    assert stats["total_games"] == 1 and stats["most_played"]["hours"] == 1.5
    library_api.invalidate_cache()
    monkeypatch.setattr(acct, "api", lambda path, **_: {"games": [], "private": True})
    with pytest.raises(library_api.LibraryError, match="private"):
        library_api.get_library_stats("7")


def test_discord_watchlist_upload(data_dir, monkeypatch):
    """Nothing leaves the app until Discord is linked; then only wishlist games,
    their real lows, region and language — and only when something changed."""
    import data.repository as repo
    from services import discord_alerts, steamkustom_auth as acct
    from services._http import ApiError
    from tests.conftest import sample_games
    from ui.settings_loader import save_settings
    repo.add_many(sample_games())
    save_settings({"country": "mx", "locale": "es"})
    calls = []
    monkeypatch.setattr(acct, "get_token", lambda: "pmsa_x")
    monkeypatch.setattr(acct, "api", lambda path, method="GET", json_body=None, **_:
                        calls.append((path, method, json_body)) or {"linked": True, "watched": 2})
    monkeypatch.setattr(discord_alerts, "_last_status_check", 0.0)
    discord_alerts.push_watchlist()                           # linked on the web → asks the server once
    assert calls[0][0] == "/alerts/settings" and calls[-1][0] == "/alerts/watchlist"
    path, method, body = calls[-1]
    assert (path, method) == ("/alerts/watchlist", "PUT") and body["country"] == "mx" and body["locale"] == "es"
    games = {g["app_id"]: g for g in body["games"]}
    assert set(games) == {"1245620", "1145350"}               # Celeste is purchased → not watched
    assert games["1245620"]["priority"] == "S" and games["1245620"]["low"] == 29.99
    assert games["1145350"]["low"] is None
    n = len(calls)
    assert discord_alerts.push_watchlist() == {"skipped": "unchanged"} and len(calls) == n

    def gone(path, method="GET", json_body=None, **_):
        raise ApiError(409, "Link Discord first")
    monkeypatch.setattr(acct, "api", gone)
    assert discord_alerts.push_watchlist(force=True) == {"skipped": "not linked"}
    assert not discord_alerts.is_linked_cached()


def test_discord_is_linked_on_the_website(data_dir):
    from services import discord_alerts, steamkustom_auth as acct
    acct._creds_cache = None
    assert discord_alerts.web_settings_url() == "https://pimpmysteam.com/settings?tab=alerts"
    acct.save_token("tok", "https://api.example.org/")
    assert discord_alerts.web_settings_url() == "https://example.org/settings?tab=alerts"
    acct.save_token("tok", "http://localhost:8000")
    assert discord_alerts.web_settings_url() == "https://pimpmysteam.com/settings?tab=alerts"
    acct.clear_token()


def test_version_and_update_check(data_dir, monkeypatch):
    import config
    from services import update_check as uc
    assert config.APP_VERSION == (config.Path(__file__).parent.parent / "VERSION").read_text().strip() \
        if hasattr(config, "Path") else config.APP_VERSION != "0.0.0"
    assert uc.is_newer("2.1.0", "2.0.0") and uc.is_newer("v2.0.1", "2.0.0") and uc.is_newer("2.0.0", "1.0.10")
    assert not uc.is_newer("2.0.0", "2.0.0") and not uc.is_newer("2.0.0-beta", "2.0.0")
    assert not uc.is_newer("1.0.10", "2.0.0")

    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"tag_name": "v9.9.9", "html_url": "https://github.com/Huzzama/Steam-Curated/releases/tag/v9.9.9"}
    calls = []
    from services import _http
    monkeypatch.setattr(_http.SESSION, "get", lambda *a, **k: (calls.append(a), _R())[1])
    r = uc.check()
    assert r["newer"] and r["latest"] == "9.9.9" and len(calls) == 1
    assert uc.check()["latest"] == "9.9.9" and len(calls) == 1          # cached for a day
    assert uc.latest_known()["newer"]
    monkeypatch.setattr(_http.SESSION, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert uc.check(force=True) is None                                 # offline → no error
