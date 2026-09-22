import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Point every repository/settings file at a temp folder."""
    import config
    import data.repository as repo
    import data.purchase_repository as prepo
    import ui.settings_loader as sl
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    (tmp_path / "assets" / "covers").mkdir(parents=True)
    repo._invalidate()
    prepo.invalidate()
    if hasattr(sl, "_cache"):
        sl._cache = None
    yield tmp_path
    repo._invalidate()
    prepo.invalidate()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    from ui import theme
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    import i18n
    i18n.load_locale("en")
    return app


def sample_games():
    from data.models import Game, PriceInfo, PriceHistory
    return [
        Game(0, "Elden Ring", "1245620", "", "Action RPG", 2022, "FromSoftware", "Bandai Namco", "", "",
             "S", "Wishlist", PriceInfo(35.99, 59.99, "USD", 40, True), PriceHistory(29.99, "2025-06-27", 50, None, None)),
        Game(0, "Hades II", "1145350", "", "Roguelike", 2024, "Supergiant", "Supergiant", "", "",
             "A", "Wishlist", PriceInfo(29.99, 29.99, "USD", 0, False), None),
        Game(0, "Celeste", "504230", "", "Platformer", 2018, "Maddy", "Maddy", "", "",
             "C", "Purchased", PriceInfo(4.99, 19.99, "USD", 75, True), None),
    ]
