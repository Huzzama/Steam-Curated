from ui.history_settings_views import load_settings


def get_settings() -> dict:
    return load_settings()


def save_settings(data: dict) -> None:
    """Save settings dict to settings.json."""
    import json
    from config import BASE_DIR
    path = BASE_DIR / "settings.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)