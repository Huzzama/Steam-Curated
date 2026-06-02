from pathlib import Path

BASE_DIR    = Path(__file__).parent
ASSETS_DIR  = BASE_DIR / "assets"
COVERS_DIR  = ASSETS_DIR / "covers"
LOCALES_DIR = BASE_DIR / "locales"
EXCEL_PATH  = BASE_DIR / "biblioteca.xlsx"

COVERS_DIR.mkdir(parents=True, exist_ok=True)

STEAMGRIDDB_API_KEY = "YOUR_STEAMGRIDDB_API_KEY"
STEAM_API_BASE   = "https://store.steampowered.com/api"
STEAMGRIDDB_BASE = "https://www.steamgriddb.com/api/v2"
STEAMDB_BASE     = "https://steamdb.info/app"

APP_NAME        = "Steam Curator"
WINDOW_SIZE     = "1200x720"
MIN_WINDOW_SIZE = (900, 600)

# ── New dark cold palette ─────────────────────────────────────────────────────
COLORS = {
    "bg":         "#09090b",   # zinc-950 — near black
    "panel":      "#0f0f12",   # slightly lighter panel
    "card":       "#141418",   # card background
    "card_hover": "#1c1c22",   # hover state
    "blue":       "#60a5fa",   # cold blue-400
    "blue_dim":   "#1d4ed8",   # blue-700 for subtle fills
    "green":      "#4ade80",   # green-400
    "text":       "#f4f4f5",   # zinc-100
    "text_dim":   "#71717a",   # zinc-500
    "border":     "#27272a",   # zinc-800
    "gold":       "#fbbf24",   # amber-400
    "red":        "#f87171",   # red-400
}

PRIORITY_COLORS = {
    "S": "#fbbf24",   # amber — must buy
    "A": "#4ade80",   # green — very important
    "B": "#60a5fa",   # cold blue — interesting
    "C": "#52525b",   # zinc-600 — low priority
}

STATUS_OPTIONS   = ["Wishlist", "Archivado"]
PRIORITY_OPTIONS = ["S", "A", "B", "C"]

# ── Steam Sale Events 2026-2027 ───────────────────────────────────────────────
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