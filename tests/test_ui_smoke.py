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
