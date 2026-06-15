#!/usr/bin/env bash
# Build Steam Curator for macOS (.app + .dmg)
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "▸ Installing dependencies…"
pip install pyinstaller pillow requests python-i18n \
    google-auth google-auth-oauthlib google-api-python-client \
    matplotlib numpy pandas openpyxl beautifulsoup4 lxml \
    python-jose cryptography pyotp PySide6

echo "▸ Building .app bundle…"
pyinstaller packaging/build.spec --clean --noconfirm

echo "▸ Creating .dmg…"
if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "Steam Curator" \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "Steam Curator.app" 150 190 \
        --app-drop-link 450 190 \
        "dist/SteamCurator-macOS.dmg" \
        "dist/Steam Curator.app" 2>/dev/null || \
    hdiutil create -volname "Steam Curator" \
        -srcfolder "dist/Steam Curator.app" \
        -ov -format UDZO \
        "dist/SteamCurator-macOS.dmg"
else
    hdiutil create -volname "Steam Curator" \
        -srcfolder "dist/Steam Curator.app" \
        -ov -format UDZO \
        "dist/SteamCurator-macOS.dmg"
fi

echo "✓ Done: dist/SteamCurator-macOS.dmg"
