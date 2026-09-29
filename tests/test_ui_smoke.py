"""Every view and dialog builds, refreshes, retranslates and renders offscreen."""
import pytest

import data.repository as repo
from tests.conftest import sample_games

VIEWS = ["wishlist", "library", "dashboard", "deals", "non_steam", "history", "recap", "settings"]


@pytest.fixture()
def window(qapp, data_dir):
    repo.add_many(sample_games())
    from ui.app_window import AppWindow
    w = AppWindow()
    w.resize(1200, 720)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


@pytest.mark.parametrize("key", VIEWS)
def test_view_builds_and_renders(window, qapp, key):
    window.show_view(key)
    qapp.processEvents()
    view = window.view(key)
    assert view is not None
    view.refresh(force=True)
    if hasattr(view, "retranslate"):
        view.retranslate()
    qapp.processEvents()
    assert not window.grab().isNull()


def test_detail_panel_and_data_changed(window, qapp):
    game = repo.get_all()[0]
    window.open_detail(game)
    qapp.processEvents()
    assert window._detail_open
    window.on_data_changed()
    window.close_detail()
    qapp.processEvents()
    assert not window._detail_open


def test_locale_change_keeps_views(window, qapp):
    import i18n
    window.show_view("dashboard")
    i18n.load_locale("es")
    window.on_locale_change()
    qapp.processEvents()
    assert window.sidebar._buttons["wishlist"].text() == i18n.t("nav.wishlist")
    i18n.load_locale("en")
    window.on_locale_change()


def test_dialogs_build(window, qapp):
    from ui.add_game_dialog import AddGameDialog, extract_app_id
    from ui.mark_purchased_dialog import MarkPurchasedDialog
    assert extract_app_id("https://store.steampowered.com/app/1245620/ELDEN_RING/") == "1245620"
    assert extract_app_id("1245620") == "1245620"
    d = AddGameDialog(window, on_success=lambda *a, **k: None)
    d.show(); qapp.processEvents(); d.close()
    m = MarkPurchasedDialog(window, repo.get_all()[0], on_success=lambda *a, **k: None)
    m.show(); qapp.processEvents(); m.close()


def test_empty_state(qapp, data_dir):
    from ui.app_window import AppWindow
    w = AppWindow(); w.show(); qapp.processEvents()
    for key in VIEWS:
        w.show_view(key); qapp.processEvents()
    w.close()


@pytest.mark.parametrize("width", [280, 340, 400, 640])   # 280: stress (fonts differ per OS)
@pytest.mark.parametrize("locale", ["en", "es", "de"])
def test_detail_panel_never_overflows(qapp, data_dir, width, locale):
    """Nothing inside the detail panel may extend past its right edge (MXN prices,
    long genre/developer lists, long region names, every locale)."""
    import i18n
    from PySide6.QtWidgets import QWidget
    from data.models import PriceInfo
    from services import deal_history
    from ui.game_detail_panel import GameDetailPanel
    i18n.load_locale(locale)
    try:
        g = sample_games()[0]
        g.genre = "Action, RPG, Adventure, Open World, Souls-like"
        g.developer = "FromSoftware Inc., Bandai Namco Entertainment, QLOC S.A."
        g.price = PriceInfo(71999.80, 119999.80, "MXN", 40, True)
        repo.add_many([g])
        g = repo.get_all()[0]
        for y in (2023, 2024, 2025):
            deal_history.record(g.app_id, 60, f"{y}-06-27")
            deal_history.record(g.app_id, 0, f"{y}-07-10")
        panel = GameDetailPanel(on_close=lambda: None)
        panel.resize(width, 800)
        panel.show()
        panel.load_game(g)
        panel._region_order = ["mx", "us", "ar", "br"]
        panel._render_regions({"mx": g.price, "us": PriceInfo(35.99, 59.99, "USD", 40, True),
                               "ar": PriceInfo(123456.99, 205761.65, "ARS", 40, True), "br": None})
        qapp.processEvents()
        content = panel._scroll.widget()
        vw = panel._scroll.viewport().width()
        assert content.width() <= vw
        for w in content.findChildren(QWidget):
            if not w.isVisibleTo(content) or w.width() == 0:
                continue
            right = w.mapTo(content, w.rect().topRight()).x()
            assert right <= vw, f"{type(w).__name__} {getattr(w, 'text', lambda: '')()!r} ends at {right} > {vw}"
        panel.close()
    finally:
        i18n.load_locale("en")


def test_region_comparison_colours(qapp, data_dir):
    """Foreign prices show '≈ local · N % cheaper' (green) or '… more expensive' (red)."""
    import i18n
    from data.models import PriceInfo
    from ui.game_detail_panel import GameDetailPanel
    from ui.theme import C
    i18n.load_locale("en")
    table = {"USD": 1.0, "MXN": 20.0, "GBP": 0.8}
    txt, color = GameDetailPanel._compare_text(34.99 * 20, 459.99, "MXN")
    assert "more expensive" in txt and color == C["red"] and "52%" in txt
    txt, color = GameDetailPanel._compare_text(300.0, 459.99, "MXN")
    assert "35% cheaper" in txt and color == C["green"]
    repo.add_many(sample_games()[:1])
    g = repo.get_all()[0]
    g.price = PriceInfo(459.99, 459.99, "MXN", 0, False)
    panel = GameDetailPanel(on_close=lambda: None)
    panel._game = g
    panel._fx = (table, {"source": "live", "date": "2026-09-28"})
    panel._region_order = ["mx", "us", "gb"]
    panel._render_regions({"mx": g.price, "us": PriceInfo(34.99, 34.99, "USD", 0, False),
                           "gb": PriceInfo(9.99, 19.99, "GBP", 50, True)})
    texts = [w.text() for w in panel._region_card.findChildren(type(panel._eyebrow))]
    joined = " | ".join(texts)
    assert "more expensive" in joined and "cheaper" in joined and "ExchangeRate-API" in joined


def test_detail_shows_purchase_verification(qapp, data_dir, monkeypatch):
    import i18n
    from data import purchase_repository as prepo
    from data.models import Purchase
    from services import steamkustom_auth as acct
    from ui.game_detail_panel import GameDetailPanel
    i18n.load_locale("en")
    monkeypatch.setattr(acct, "get_token", lambda: "pmsa_x")
    repo.add_many(sample_games()[:1])
    g = repo.get_all()[0]
    prepo.add(Purchase(g.app_id, g.name, "2026-09-01", 20.0, 60.0, "USD", 66, "Deluxe", 40.0,
                       kind="edition", verification="partial",
                       verified_items=[{"app_id": g.app_id, "state": "owned"},
                                       {"app_id": "2", "state": "missing"},
                                       {"app_id": "3", "state": "unverifiable"}]))
    panel = GameDetailPanel(on_close=lambda: None)
    panel.load_game(g)
    assert panel._verify_pill.text() == "PARTLY VERIFIED"
    assert "1 of 2 games" in panel._verify_text.toolTip() and "1 DLC" in panel._verify_text.toolTip()
    assert not panel._verify_btn.isHidden()


def test_settings_discord_alerts_states(window, qapp, monkeypatch):
    from services import steamkustom_auth as acct
    window.show_view("settings")
    view = window.view("settings")
    qapp.processEvents()
    assert view._alerts_link_btn.isHidden() and view._alerts_opts.isHidden()      # no account
    monkeypatch.setattr(acct, "is_connected", lambda: True)
    view._alerts = {"configured": True, "linked": False}
    view._render_alerts()
    assert not view._alerts_link_btn.isHidden() and view._alerts_opts.isHidden()
    view._alerts = {"configured": True, "linked": True, "discord_username": "ryu", "enabled": True,
                    "on_sale": True, "at_low": True, "daily_digest": False, "watched": 51, "country": "mx",
                    "last_error": "dm_closed"}
    view._render_alerts()
    assert view._alerts_link_btn.isHidden() and not view._alerts_opts.isHidden()
    assert view._alert_chips["daily_digest"].property("active") == "false"
    assert "ryu" in view._alerts_status.text() and not view._alerts_error.isHidden()
