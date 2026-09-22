# Steam Curator

Desktop companion for your Steam wishlist: priorities, live prices, all-time
lows, sale countdowns, purchase history and a yearly recap — with a
PimpMySteam account for wishlist import and Google Drive backups.

Built with Python 3.11+ and PySide6. Runs on Windows, macOS and Linux.

## Run from source

```bash
pip install -r requirements.txt
python main.py
```

## Configuration (Settings screen)

| What | Where it comes from |
|---|---|
| PimpMySteam account | Token generated at pimpmysteam.com › Settings › Apps. Enables wishlist import, Steam library stats and Drive backup. Stored in `creds.json` next to your data (mode 600). |
| Price history / all-time low | Free [IsThereAnyDeal](https://isthereanydeal.com/apps/my/) API key. |
| Covers | Optional SteamGridDB key; Steam header art is used as a fallback. |
| Locale, country, timezone, comparison regions | Preferences card. |

Data lives in `wishlist.json`, `purchases.json`, `settings.json`, `creds.json`
and `assets/covers/` — in the project folder when running from source, or in
the per-user app-data folder when packaged. Every write is atomic and keeps a
`.bak`; logs go to `logs/curator.log`.

## Project layout

```
main.py                 entry point (logging, Drive sync, theme, window)
ui/theme.py             design tokens, bundled fonts, global QSS
ui/icons.py             Lucide icons rendered from SVG
ui/components.py        buttons, cards, fields, stat tiles, toasts…
ui/app_window.py        shell: sidebar, animated view stack, detail panel
ui/<view>_view.py       one file per screen (refresh(force) / retranslate())
ui/async_bridge.py      run_async(): work off the GUI thread, result back on it
services/               Steam store, ITAD, PimpMySteam API, Drive, SteamGridDB
data/                   JSON repositories and models
locales/                26 languages; tools/merge_locales.py keeps them in sync
tools/shot.py           headless screenshot of any view with sample data
tests/                  pytest (services, repositories, locales, UI smoke)
```

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
```

## Packaging

See `packaging/README.md` (`packaging/build.spec` for PyInstaller).

## Credits

Fonts: Inter, Space Mono, Bebas Neue (SIL OFL — licences in `assets/fonts/`).
Icons: [Lucide](https://lucide.dev) (ISC — `assets/LICENSE-lucide.txt`).
