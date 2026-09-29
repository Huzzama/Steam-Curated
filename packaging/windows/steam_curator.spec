# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# steam_curator.spec — PyInstaller bundle spec (Windows)
#
# From the repo root:
#   pyinstaller packaging\windows\steam_curator.spec --noconfirm --clean
#
# Output: dist\SteamCurator\SteamCurator.exe  (folder build → Inno Setup)
# ─────────────────────────────────────────────────────────────────────────────
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ICON = os.path.join(ROOT, "assets", "icon.ico")      # a real .ico: taskbar + installer icon

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
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SteamCurator",
          console=False, strip=False, upx=False, icon=ICON)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SteamCurator")
