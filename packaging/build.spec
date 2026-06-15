# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

def find_icon(exts):
    for ext in exts:
        for d in [ROOT / 'assets', ROOT / 'app' / 'assets', ROOT]:
            p = d / f'icon{ext}'
            if p.exists(): return str(p)
    return None

block_cipher = None

datas = []
for folder in ['locales', 'assets', 'app/assets']:
    p = ROOT / folder
    if p.exists():
        datas.append((str(p), folder))

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # PySide6 — core
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtNetwork',
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtMultimedia',
        # PIL
        'PIL', 'PIL._tkinter_finder',
        'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter',
        'PIL.ImageFont', 'PIL.ImageTk',
        'PIL.JpegImagePlugin', 'PIL.PngImagePlugin',
        'PIL.BmpImagePlugin', 'PIL.GifImagePlugin',
        # Matplotlib
        'matplotlib', 'matplotlib.pyplot',
        'matplotlib.backends.backend_qt5agg',
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_agg',
        'matplotlib.figure',
        # Google
        'google.auth', 'google.auth.transport.requests',
        'google.oauth2.credentials',
        'google_auth_oauthlib', 'google_auth_oauthlib.flow',
        'googleapiclient', 'googleapiclient.discovery',
        'googleapiclient.http',
        # Requests / networking
        'requests', 'requests.packages.urllib3',
        'urllib3', 'certifi', 'charset_normalizer',
        # i18n
        'i18n', 'i18n.loaders', 'i18n.config',
        # Data
        'openpyxl', 'openpyxl.styles', 'openpyxl.utils',
        'pandas', 'pandas.io.formats.style',
        'bs4', 'lxml', 'html.parser',
        # Auth
        'jose', 'jose.jwt', 'jose.exceptions',
        'cryptography',
        # Other
        'packaging', 'dateutil', 'pytz',
        'numpy', 'six', 'pyotp',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['pytest', 'test', 'tests', 'IPython', 'jupyter',
              'tkinter', 'customtkinter', '_tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SteamCurator',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Steam Curator.app',
        icon=icon,
        bundle_identifier='com.pimpmysteam.curator',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'LSMinimumSystemVersion': '11.0',
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
            'CFBundleName': 'Steam Curator',
            'CFBundleDisplayName': 'Steam Curator',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'CFBundleIconFile': 'icon',
            'NSDocumentsFolderUsageDescription': 'Steam Curator needs access to save your wishlist data.',
            'NSDesktopFolderUsageDescription': 'Steam Curator needs access to your desktop.',
        },
    )
