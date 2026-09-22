"""
Headless screenshot of one view / dialog with sample data.

    QT_QPA_PLATFORM=offscreen python3 tools/shot.py wishlist /tmp/shots/wishlist.png
    QT_QPA_PLATFORM=offscreen python3 tools/shot.py detail   /tmp/shots/detail.png
    QT_QPA_PLATFORM=offscreen python3 tools/shot.py add      /tmp/shots/add.png
    QT_QPA_PLATFORM=offscreen python3 tools/shot.py purchase /tmp/shots/purchase.png

Options: --locale es  --size 1200x720  --delay 900 (ms before grabbing)
Data lives in a throw-away folder so the real wishlist.json is never touched.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

VIEW_KEYS = ["wishlist", "library", "dashboard", "deals", "non_steam", "history", "recap", "settings"]

_GAMES = [
    ("Hades II", "1145350", "Roguelike", 2024, "Supergiant Games", "S", 29.99, 29.99, 0, 21.99, "2025-12-22", 25, "playing"),
    ("Elden Ring", "1245620", "Action RPG", 2022, "FromSoftware", "S", 35.99, 59.99, 40, 29.99, "2025-06-27", 50, ""),
    ("Hollow Knight: Silksong", "1030300", "Metroidvania", 2025, "Team Cherry", "S", 19.99, 19.99, 0, 19.99, "2025-09-04", 0, ""),
    ("Baldur's Gate 3", "1086940", "RPG", 2023, "Larian Studios", "A", 47.99, 59.99, 20, 41.99, "2024-11-28", 30, "completed"),
    ("Stardew Valley", "413150", "Simulation", 2016, "ConcernedApe", "A", 8.99, 14.99, 40, 7.49, "2024-06-27", 50, ""),
    ("Cyberpunk 2077", "1091500", "RPG", 2020, "CD PROJEKT RED", "A", 29.99, 59.99, 50, 23.99, "2025-03-13", 60, "on_hold"),
    ("Slay the Spire 2", "2868840", "Deckbuilder", 2026, "Mega Crit", "B", 24.99, 24.99, 0, 0, None, 0, ""),
    ("Dave the Diver", "1868140", "Adventure", 2023, "MINTROCKET", "B", 11.99, 19.99, 40, 9.99, "2025-01-02", 50, ""),
    ("Sea of Stars", "1244090", "RPG", 2023, "Sabotage Studio", "B", 34.99, 34.99, 0, 17.49, "2025-06-26", 50, ""),
    ("Balatro", "2379780", "Card", 2024, "LocalThunk", "C", 14.99, 14.99, 0, 11.24, "2025-12-19", 25, "abandoned"),
    ("Celeste", "504230", "Platformer", 2018, "Maddy Makes Games", "C", 4.99, 19.99, 75, 3.99, "2024-12-19", 80, ""),
    ("Outer Wilds", "753640", "Exploration", 2019, "Mobius Digital", "C", 24.99, 24.99, 0, 9.99, "2025-06-26", 60, ""),
]


def make_fixture(folder: Path) -> None:
    games = []
    for i, (name, appid, genre, year, dev, prio, cur, base, disc, low, low_date, low_disc, play) in enumerate(_GAMES, 1):
        games.append({
            "id": i, "name": name, "app_id": appid,
            "steam_url": f"https://store.steampowered.com/app/{appid}",
            "genre": genre, "release_year": year, "developer": dev, "publisher": dev,
            "categories": "Single-player", "short_description": f"{name} — sample description for the screenshot tool.",
            "priority": prio, "status": "Purchased" if i in (4, 11) else "Wishlist",
            "price": {"current": cur, "base": base, "currency": "USD", "discount_pct": disc, "is_on_sale": disc > 0},
            "price_history": None if low == 0 else {"all_time_low": low, "all_time_low_date": low_date,
                                                   "all_time_discount": low_disc, "last_sale_price": None, "last_sale_date": None},
            "personal_rating": None, "notes": "", "cover_path": None,
            "date_added": f"2026-0{(i % 8) + 1}-1{i % 9}", "play_status": play,
        })
    (folder / "wishlist.json").write_text(json.dumps(games, indent=2), encoding="utf-8")
    purchases = [
        {"app_id": "1086940", "name": "Baldur's Gate 3", "purchased_at": "2025-11-28", "price_paid": 41.99,
         "base_price": 59.99, "currency": "USD", "discount_pct": 30, "edition": "Standard", "saved": 18.0},
        {"app_id": "504230", "name": "Celeste", "purchased_at": "2025-12-19", "price_paid": 3.99,
         "base_price": 19.99, "currency": "USD", "discount_pct": 80, "edition": "Standard", "saved": 16.0},
        {"app_id": "2379780", "name": "Balatro", "purchased_at": "2026-01-03", "price_paid": 11.24,
         "base_price": 14.99, "currency": "USD", "discount_pct": 25, "edition": "Standard", "saved": 3.75},
    ]
    (folder / "purchases.json").write_text(json.dumps(purchases, indent=2), encoding="utf-8")
    (folder / "settings.json").write_text(json.dumps({"locale": "en", "country": "us", "timezone": "GMT-6",
                                                      "compare_regions": ["us", "mx", "ar"]}), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="view key, or: detail | add | purchase | window")
    ap.add_argument("out")
    ap.add_argument("--locale", default="en")
    ap.add_argument("--size", default="1200x720")
    ap.add_argument("--delay", type=int, default=900)
    args = ap.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    tmp = Path(tempfile.mkdtemp(prefix="curator_shot_"))
    make_fixture(tmp)

    import config
    config.BASE_DIR = tmp                       # repositories & settings read this lazily
    (tmp / "assets" / "covers").mkdir(parents=True)
    import i18n
    i18n.load_locale(args.locale)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ui import theme
    app = QApplication(sys.argv)
    theme.apply(app)

    from ui.app_window import AppWindow
    w, h = (int(x) for x in args.size.split("x"))
    win = AppWindow()
    win.resize(w, h)
    win.show()

    import data.repository as repo
    sample_game = repo.get_all()[1]
    dlg = None

    def prepare():
        nonlocal dlg
        t = args.target
        if t in VIEW_KEYS:
            win.show_view(t)
        elif t == "detail":
            win.show_view("wishlist")
            win.open_detail(sample_game)
        elif t == "add":
            from ui.add_game_dialog import AddGameDialog
            dlg = AddGameDialog(win, on_success=lambda *a, **k: None)
            dlg.show()
        elif t == "purchase":
            from ui.mark_purchased_dialog import MarkPurchasedDialog
            dlg = MarkPurchasedDialog(win, sample_game, on_success=lambda *a, **k: None)
            dlg.show()
        elif t == "window":
            pass
        else:
            sys.exit(f"unknown target {t!r}; views: {VIEW_KEYS}")

    def grab():
        target = dlg if dlg is not None else win
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        target.grab().save(args.out)
        print("saved", args.out)
        app.quit()

    QTimer.singleShot(200, prepare)
    QTimer.singleShot(200 + args.delay, grab)
    app.exec()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
