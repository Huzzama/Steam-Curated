# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# steam_curator_mac.spec — PyInstaller bundle spec (macOS)
#
# From the repo root:
#   pyinstaller packaging/macos/steam_curator_mac.spec \
#     --distpath packaging/macos/dist --workpath packaging/macos/build --noconfirm
#
# Output: packaging/macos/dist/Steam Curator.app
# CFBundleVersion / CFBundleShortVersionString come from the VERSION file.
# ─────────────────────────────────────────────────────────────────────────────
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent.parent
APP_VERSION = (ROOT / "VERSION").read_text().strip()
ICON = str(ROOT / "assets" / "icon.icns")     # made by release.yml from assets/icon.png

datas = [
    (str(ROOT / "locales"), "locales"),
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
    (str(ROOT / "assets" / "icon.png"), "assets"),
    (str(ROOT / "assets" / "LICENSE-lucide.txt"), "assets"),
    (str(ROOT / "VERSION"), "."),
]

hiddenimports = (collect_submodules("ui") + collect_submodules("services") + collect_submodules("data")
                 + ["i18n", "config", "PySide6.QtSvg", "PySide6.QtNetwork", "logging.handlers"])

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "numpy", "IPython", "notebook", "pytest",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf"],
    noarchive=False,
)
def _keep(entry):
    dest = entry[0].replace("\\", "/")
    return "discovery_cache/documents/" not in dest or dest.endswith("/drive.v3.json")
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SteamCurator",
          console=False, strip=False, upx=False, icon=ICON)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SteamCurator")
app = BUNDLE(
    coll,
    name="Steam Curator.app",
    icon=ICON,
    bundle_identifier="com.pimpmysteam.curator",
    info_plist={
        "CFBundleName": "Steam Curator",
        "CFBundleDisplayName": "Steam Curator",
        "CFBundleIdentifier": "com.pimpmysteam.curator",
        "CFBundleVersion": APP_VERSION,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleIconFile": "icon.icns",
        "CFBundlePackageType": "APPL",
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "NSSupportsAutomaticGraphicsSwitching": True,
        "LSMinimumSystemVersion": "11.0",
    },
)
