# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

# Find icon — support .png, .jpg, .ico, .icns
def find_icon(exts):
    for ext in exts:
        p = ROOT / 'assets' / f'icon{ext}'
        if p.exists(): return str(p)
    # Also check root directory
    for ext in exts:
        p = ROOT / f'icon{ext}'
        if p.exists(): return str(p)
    return None

block_cipher = None

# Build datas list
datas = [(str(ROOT / 'locales'), 'locales')]
if (ROOT / 'assets').exists():
    datas.append((str(ROOT / 'assets'), 'assets'))

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'customtkinter',
        'PIL._tkinter_finder',
        'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter', 'PIL.ImageFont',
        'PIL.JpegImagePlugin', 'PIL.PngImagePlugin',
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
    excludes=['pytest', 'test', 'tests'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Icon per platform
if sys.platform == 'darwin':
    icon = find_icon(['.icns', '.png', '.jpg', '.jpeg'])
elif sys.platform == 'win32':
    icon = find_icon(['.ico', '.png', '.jpg', '.jpeg'])
else:
    icon = find_icon(['.png', '.jpg', '.jpeg'])

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='SteamCurator',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon=icon,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='SteamCurator',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Steam Curator.app',
        icon=icon,
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
