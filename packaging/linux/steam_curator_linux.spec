# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# steam_curator_linux.spec — PyInstaller bundle spec (Linux)
#
# Used by the AppImage, the .deb and the .rpm (release.yml). From the repo root:
#   pyinstaller packaging/linux/steam_curator_linux.spec --noconfirm --clean
#
# Output: dist/steam-curator/steam-curator (folder bundle — starts much faster
# inside an AppImage than a one-file binary that unpacks itself on every launch).
#
# Resources (locales, assets/fonts, VERSION) land next to the bundled code
# (sys._MEIPASS = dist/steam-curator/_internal), which is what
# config.BUNDLE_DIR resolves to in a frozen build.
# ─────────────────────────────────────────────────────────────────────────────
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

datas = [
    (os.path.join(ROOT, "locales"), "locales"),
    (os.path.join(ROOT, "assets", "fonts"), "assets/fonts"),
    (os.path.join(ROOT, "assets", "icon.png"), "assets"),
    (os.path.join(ROOT, "assets", "LICENSE-lucide.txt"), "assets"),
    (os.path.join(ROOT, "VERSION"), "."),
]

hiddenimports = (collect_submodules("ui") + collect_submodules("services") + collect_submodules("data")
                 + ["i18n", "config", "PySide6.QtSvg", "PySide6.QtNetwork", "logging.handlers"])

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "numpy", "IPython", "notebook", "pytest",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf"],
    noarchive=False,
)
# googleapiclient ships ~100 MB of discovery documents for every Google API;
# the app only talks to Drive v3.
def _keep(entry):
    dest = entry[0].replace("\\", "/")
    return "discovery_cache/documents/" not in dest or dest.endswith("/drive.v3.json")
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="steam-curator", console=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="steam-curator")
