import sys
from pathlib import Path

# ── Base directories ───────────────────────────────────────────────────────────
# When running as a PyInstaller bundle, use user data directory
# so we never write to the read-only .app bundle
def _get_base_dir() -> Path:
    """
    Returns writable base directory for user data.
    - Bundled (.app/.exe): ~/Library/Application Support/SteamCurator (mac)
                           %APPDATA%/SteamCurator (win)
                           ~/.local/share/SteamCurator (linux)
    - Dev (running from source): project root
    """
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        if sys.platform == 'darwin':
            base = Path.home() / 'Library' / 'Application Support' / 'SteamCurator'
        elif sys.platform == 'win32':
            import os
            base = Path(os.environ.get('APPDATA', Path.home())) / 'SteamCurator'
        else:
            base = Path.home() / '.local' / 'share' / 'SteamCurator'
        base.mkdir(parents=True, exist_ok=True)
        return base
    else:
        # Running from source — use project root
        return Path(__file__).parent

def _get_bundle_dir() -> Path:
    """Returns the directory where the bundled resources live (read-only in .app)."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent

BASE_DIR    = _get_base_dir()
BUNDLE_DIR  = _get_bundle_dir()

# Writable data paths (user data dir)
ASSETS_DIR  = BASE_DIR / "assets"
COVERS_DIR  = ASSETS_DIR / "covers"
EXCEL_PATH  = BASE_DIR / "biblioteca.xlsx"

# Read-only resource paths (inside bundle)
LOCALES_DIR = BUNDLE_DIR / "locales"

# Create writable dirs
COVERS_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

STEAMGRIDDB_API_KEY = "YOUR_STEAMGRIDDB_API_KEY"
STEAM_API_BASE   = "https://store.steampowered.com/api"
STEAMGRIDDB_BASE = "https://www.steamgriddb.com/api/v2"
STEAMDB_BASE     = "https://steamdb.info/app"

APP_NAME        = "Steam Curator"
WINDOW_SIZE     = "1200x720"
MIN_WINDOW_SIZE = (900, 600)

# ── New dark cold palette ─────────────────────────────────────────────────────
COLORS = {
    "bg":         "#09090b",
    "panel":      "#0f0f12",
    "card":       "#141418",
    "card_hover": "#1c1c22",
    "blue":       "#60a5fa",
    "blue_dim":   "#1d4ed8",
    "green":      "#4ade80",
    "text":       "#f4f4f5",
    "text_dim":   "#71717a",
    "border":     "#27272a",
    "gold":       "#fbbf24",
    "red":        "#f87171",
}

PRIORITY_COLORS = {
    "S": "#fbbf24",
    "A": "#4ade80",
    "B": "#60a5fa",
    "C": "#52525b",
}

STATUS_OPTIONS   = ["Wishlist", "Archivado"]
PRIORITY_OPTIONS = ["S", "A", "B", "C"]

# ── Steam Sale Events ─────────────────────────────────────────────────────────
STEAM_SALE_EVENTS = [
    {"key": "summer_sale_2026",    "start": "2026-06-25", "end": "2026-07-09",
     "confirmed": False, "color_top": "#1A6B9A", "color_bot": "#0D3550", "emoji": "☀️"},
    {"key": "halloween_sale_2026", "start": "2026-10-27", "end": "2026-10-31",
     "confirmed": False, "color_top": "#6C3483", "color_bot": "#2C1654", "emoji": "🎃"},
    {"key": "black_friday_2026",   "start": "2026-11-25", "end": "2026-11-29",
     "confirmed": False, "color_top": "#1C1C1C", "color_bot": "#111111", "emoji": "🖤"},
    {"key": "autumn_sale_2026",    "start": "2026-11-25", "end": "2026-12-02",
     "confirmed": False, "color_top": "#A04000", "color_bot": "#5D2E0C", "emoji": "🍂"},
    {"key": "winter_sale_2026",    "start": "2026-12-17", "end": "2027-01-01",
     "confirmed": False, "color_top": "#154360", "color_bot": "#0B2742", "emoji": "❄️"},
    {"key": "lunar_new_year_2027", "start": "2027-01-28", "end": "2027-02-04",
     "confirmed": False, "color_top": "#C0392B", "color_bot": "#7B241C", "emoji": "🧧"},
    {"key": "spring_sale_2027",    "start": "2027-03-11", "end": "2027-03-18",
     "confirmed": False, "color_top": "#1E8449", "color_bot": "#0E5230", "emoji": "🌸"},
    {"key": "summer_sale_2027",    "start": "2027-06-24", "end": "2027-07-08",
     "confirmed": False, "color_top": "#1A6B9A", "color_bot": "#0D3550", "emoji": "☀️"},
]

SHEET_WISHLIST  = "Wishlist"
SHEET_DASHBOARD = "Dashboard"

LOCALES = {
    "es": "Español",
    "en": "English",
    "ja": "日本語",
    "pt": "Português",
    "fr": "Français",
}
DEFAULT_LOCALE = "es"