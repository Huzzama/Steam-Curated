# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Steam Curator

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

block_cipher = None

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'locales'), 'locales'),
        (str(ROOT / 'assets' / 'fonts'), 'assets/fonts')
        if (ROOT / 'assets' / 'fonts').exists() else
        (str(ROOT / 'assets'), 'assets'),
    ],
    hiddenimports=[
        'customtkinter',
        'PIL._tkinter_finder',
        'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter', 'PIL.ImageFont',
        'matplotlib', 'matplotlib.backends.backend_tkagg',
        'matplotlib.backends.backend_agg',
        'google.auth', 'google.auth.transport.requests',
        'google.oauth2.credentials',
        'google_auth_oauthlib.flow',
        'googleapiclient.discovery',
        'googleapiclient.http',
        'requests', 'requests.packages.urllib3',
        'i18n', 'i18n.loaders',
        'openpyxl', 'pandas', 'bs4',
        'jose', 'jose.jwt',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['pytest', 'test', 'tests', 'tkinter.test'],
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
    console=False,
    icon=str(ROOT / 'assets' / 'icon.ico')
        if (ROOT / 'assets' / 'icon.ico').exists() else None,
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

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Steam Curator.app',
        icon=str(ROOT / 'assets' / 'icon.icns')
            if (ROOT / 'assets' / 'icon.icns').exists() else None,
        bundle_identifier='com.steamkustom.curator',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'LSMinimumSystemVersion': '10.13.0',
            'NSHighResolutionCapable': True,
            'CFBundleName': 'Steam Curator',
            'CFBundleDisplayName': 'Steam Curator',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
        },
    )
