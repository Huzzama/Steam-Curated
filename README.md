# Steam Curator

Desktop companion for your Steam wishlist: priorities, live prices, all-time
lows, sale countdowns, purchase history and a yearly recap — with a
PimpMySteam account for wishlist import and Google Drive backups.

Built with Python 3.11+ and PySide6. Runs on Windows, macOS and Linux.

## Install

Grab the latest release from [GitHub Releases](https://github.com/Huzzama/Steam-Curated/releases/latest)
(also linked from [pimpmysteam.com/download](https://pimpmysteam.com/download)):

| File | Platform |
|---|---|
| `SteamCurator-<version>-Setup.exe` | Windows 10/11 |
| `Steam_Curator-<version>-arm64.dmg` | macOS 11+ on Apple Silicon — first launch: right-click → Open (unsigned) |
| `Steam_Curator-<version>-x86_64.AppImage` | Any Linux distro: `chmod +x`, then run it |
| `steam-curator_<version>_amd64.deb` | Ubuntu / Debian / Mint: `sudo apt install ./steam-curator_*_amd64.deb` |
| `steam-curator-<version>.x86_64.rpm` | Fedora: `sudo dnf install ./steam-curator-*.rpm` · Bazzite: `rpm-ostree install ./…rpm` |

The app tells you when a newer version is out (Settings › About has "Check for updates").

## Run from source

```bash
pip install -r requirements.txt
python main.py
python main.py --version      # prints the VERSION file
python main.py --self-test    # headless start-up check (used by the release pipeline)
```

## Configuration (Settings screen)

| What | Where it comes from |
|---|---|
| PimpMySteam account | Token generated at pimpmysteam.com › Settings › Apps. Enables wishlist import, Steam library stats and Drive backup. Stored in `creds.json` next to your data (mode 600). |
| Price history / all-time low | Nothing to configure: the app checks your wishlist prices on Steam once a day and records every sale (`deal_history.json`). Settings › Price tracking has a "Check now" button. |
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
services/               Steam store, deal history + predictor, PimpMySteam API, Drive, SteamGridDB
data/                   JSON repositories and models
locales/                26 languages; tools/merge_locales.py keeps them in sync
tools/shot.py           headless screenshot of any view with sample data
tests/                  pytest (services, repositories, locales, UI smoke)
```

## Tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
```

## Releasing

`VERSION` is the single source of truth (app, About, installers, Info.plist).

1. Add a `## [x.y.z] — date` section to `CHANGELOG.md` (it becomes the release notes).
2. Set `VERSION`, commit and push `main`.
3. `git tag vx.y.z && git push origin vx.y.z`

`.github/workflows/release.yml` then runs the tests and builds the Windows
installer (PyInstaller + Inno Setup), the macOS dmg, the AppImage, the .deb and
the .rpm — each one is started headless with `--self-test` before it is
packaged — and publishes one GitHub Release with every file and
`SHA256SUMS.txt`. "Run workflow" on the Actions page builds everything without
publishing. Local builds: `packaging/linux/build-bundle.sh`,
`packaging/appimage/build-appimage.sh`, `packaging/debian/build-deb.sh`,
`packaging/fedora/build-rpm.sh`; Windows: `packaging/windows/steam_curator.spec`
+ `steam_curator.iss`; macOS: `packaging/macos/steam_curator_mac.spec`.

## Credits

Fonts: Inter, Space Mono, Bebas Neue (SIL OFL — licences in `assets/fonts/`).
Icons: [Lucide](https://lucide.dev) (ISC — `assets/LICENSE-lucide.txt`).
