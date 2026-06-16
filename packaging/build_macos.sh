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

echo "▸ Creating .dmg with Applications shortcut…"
if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "Steam Curator" \
        --window-size 660 400 \
        --icon-size 120 \
        --icon "Steam Curator.app" 165 185 \
        --app-drop-link 495 185 \
        "dist/SteamCurator-macOS.dmg" \
        "dist/Steam Curator.app" 2>/dev/null || true
fi

# Fallback / always-works: manual DMG with Applications symlink
if [ ! -f "dist/SteamCurator-macOS.dmg" ]; then
    STAGING="$(mktemp -d)/dmg_staging"
    mkdir -p "$STAGING"
    cp -R "dist/Steam Curator.app" "$STAGING/"
    ln -s /Applications "$STAGING/Applications"
    hdiutil create \
        -volname "Steam Curator" \
        -srcfolder "$STAGING" \
        -ov -format UDZO \
        "dist/SteamCurator-macOS.dmg"
    rm -rf "$STAGING"
fi

echo "✓ Done: dist/SteamCurator-macOS.dmg"
