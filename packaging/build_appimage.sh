#!/usr/bin/env bash
# Build Steam Curator as AppImage for Linux
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "▸ Installing dependencies…"
pip install pyinstaller pillow customtkinter requests python-i18n \
    google-auth google-auth-oauthlib google-api-python-client matplotlib

echo "▸ Building binary…"
pyinstaller packaging/build.spec --clean --noconfirm

echo "▸ Creating AppDir structure…"
APPDIR="$ROOT/dist/SteamCurator.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

cp -r dist/SteamCurator/* "$APPDIR/usr/bin/"

cat > "$APPDIR/SteamCurator.desktop" << DESKTOP
[Desktop Entry]
Name=Steam Curator
Exec=SteamCurator
Icon=steamcurator
Type=Application
Categories=Game;Utility;
DESKTOP

cat > "$APPDIR/AppRun" << APPRUN
#!/bin/bash
exec "\$APPDIR/usr/bin/SteamCurator" "\$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# Copy icon if exists
if [ -f "$ROOT/assets/icon.png" ]; then
    cp "$ROOT/assets/icon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/steamcurator.png"
    cp "$ROOT/assets/icon.png" "$APPDIR/steamcurator.png"
fi

echo "▸ Building AppImage…"
if command -v appimagetool &>/dev/null; then
    appimagetool "$APPDIR" "dist/SteamCurator-Linux.AppImage"
    echo "✓ Done: dist/SteamCurator-Linux.AppImage"
else
    echo "appimagetool not found. Download from:"
    echo "https://github.com/AppImage/appimagetool/releases"
    echo ""
    echo "Then run: appimagetool $APPDIR dist/SteamCurator-Linux.AppImage"
fi
