#!/usr/bin/env bash
# Build Steam Curator for macOS (.app + .dmg)
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "▸ Installing dependencies…"
pip install pyinstaller pillow customtkinter requests python-i18n \
    google-auth google-auth-oauthlib google-api-python-client \
    matplotlib 2>/dev/null || true

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
        --background packaging/dmg_background.png \
        "dist/SteamCurator-macOS.dmg" \
        "dist/Steam Curator.app" 2>/dev/null || \
    # Fallback: simple hdiutil dmg
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
