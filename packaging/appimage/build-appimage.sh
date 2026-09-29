#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-appimage.sh — Steam Curator AppImage (x86_64)
#
#   bash packaging/appimage/build-appimage.sh
#   → packaging/appimage/Steam_Curator-<VERSION>-x86_64.AppImage
#
# Wraps the self-contained PyInstaller folder from packaging/linux/build-bundle.sh.
# Runs without FUSE (APPIMAGE_EXTRACT_AND_RUN), so it works in CI containers.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$REPO_ROOT/VERSION")"
ARCH="x86_64"
APPDIR="$SCRIPT_DIR/SteamCurator.AppDir"
OUTFILE="$SCRIPT_DIR/Steam_Curator-${VERSION}-${ARCH}.AppImage"
APPIMAGETOOL="$SCRIPT_DIR/appimagetool-${ARCH}.AppImage"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"

echo "━━ Steam Curator AppImage v${VERSION} ━━"

# 1. self-contained bundle (built + self-tested)
bash "$REPO_ROOT/packaging/linux/build-bundle.sh"
BUNDLE="$REPO_ROOT/dist/linux/steam-curator"

# 2. appimagetool
if [ ! -x "$APPIMAGETOOL" ]; then
    echo "[appimage] downloading appimagetool"
    wget -q "$APPIMAGETOOL_URL" -O "$APPIMAGETOOL"
    chmod +x "$APPIMAGETOOL"
fi

# 3. AppDir
echo "[appimage] AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$BUNDLE" "$APPDIR/usr/lib/steam-curator"
cp "$REPO_ROOT/packaging/desktop/steam-curator.desktop" "$APPDIR/"
cp "$REPO_ROOT/packaging/desktop/steam-curator.desktop" "$APPDIR/usr/share/applications/"
cp "$REPO_ROOT/assets/icon.png" "$APPDIR/steam-curator.png"
cp "$REPO_ROOT/assets/icon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/steam-curator.png"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/steam-curator/steam-curator" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# 4. AppImage
echo "[appimage] packing"
rm -f "$OUTFILE"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUTFILE"

# 5. the packed AppImage itself must start
echo "[appimage] self-test of the AppImage"
OUT="$(APPIMAGE_EXTRACT_AND_RUN=1 QT_QPA_PLATFORM=offscreen LC_ALL=C.UTF-8 HOME="$(mktemp -d)" timeout 240 "$OUTFILE" --self-test 2>&1 || true)"
echo "$OUT" | tail -3
echo "$OUT" | grep -q "SELF-TEST OK" || { echo "ERROR: AppImage self-test failed"; exit 1; }
echo "✓ $(basename "$OUTFILE")  $(du -h "$OUTFILE" | cut -f1)"
