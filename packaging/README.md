# Steam Curator — Packaging Guide

## Requirements

```bash
pip install pyinstaller
```

---

## macOS (.app + .dmg)

```bash
bash packaging/build_macos.sh
```

Output: `dist/SteamCurator-macOS.dmg`

For the DMG background image, place a 600×400 PNG at:
`packaging/dmg_background.png`

Optional — better DMG creation:
```bash
brew install create-dmg
```

For code signing (distribute outside App Store):
```bash
codesign --deep --sign "Developer ID Application: Your Name (TEAMID)" \
    "dist/Steam Curator.app"
spctl --assess --type execute "dist/Steam Curator.app"
```

---

## Windows (.exe)

```batch
packaging\build_windows.bat
```

Output: `dist/SteamCurator/` folder (portable) or installer if NSIS is installed.

For a proper installer, install [NSIS](https://nsis.sourceforge.io/) and run:
```batch
makensis packaging/installer.nsi
```

---

## Linux (AppImage)

```bash
bash packaging/build_appimage.sh
```

Output: `dist/SteamCurator-Linux.AppImage`

Requires `appimagetool`:
```bash
wget -O appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool && sudo mv appimagetool /usr/local/bin/
```

---

## Icon files needed

Place these in `assets/`:
- `icon.ico` — Windows (multi-size ICO, at least 256×256)
- `icon.icns` — macOS (use `iconutil` or `sips`)
- `icon.png` — Linux (256×256 PNG)

Convert PNG to ICNS on macOS:
```bash
mkdir icon.iconset
sips -z 256 256 assets/icon.png --out icon.iconset/icon_256x256.png
iconutil -c icns icon.iconset -o assets/icon.icns
```

Convert PNG to ICO (requires Pillow):
```python
from PIL import Image
Image.open("assets/icon.png").save("assets/icon.ico", sizes=[(256,256),(128,128),(64,64),(32,32),(16,16)])
```
