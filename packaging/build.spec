# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Steam Curator
# Usage: pyinstaller packaging/build.spec

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

block_cipher = None

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Include locale files
        (str(ROOT / 'locales'), 'locales'),
        # Include assets (covers are excluded — too large, generated at runtime)
    ],
    hiddenimports=[
        'customtkinter',
        'PIL._tkinter_finder',
        'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter',
        'matplotlib.backends.backend_tkagg',
        'google.auth', 'google.auth.transport.requests',
        'google.oauth2.credentials',
        'google_auth_oauthlib.flow',
        'googleapiclient.discovery',
        'googleapiclient.http',
        'requests',
        'i18n',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['test', 'tests', 'pytest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SteamCurator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No terminal window on Windows
    icon=str(ROOT / 'assets' / 'icon.ico') if (ROOT / 'assets' / 'icon.ico').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SteamCurator',
)

# macOS .app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Steam Curator.app',
        icon=str(ROOT / 'assets' / 'icon.icns') if (ROOT / 'assets' / 'icon.icns').exists() else None,
        bundle_identifier='com.steamkustom.curator',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'CFBundleDocumentTypes': [],
            'LSMinimumSystemVersion': '10.13.0',
            'NSHighResolutionCapable': True,
        },
    )
