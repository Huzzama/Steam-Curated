import requests
from pathlib import Path
from typing import Optional
from config import STEAMGRIDDB_BASE, COVERS_DIR


def _make_session(api_key: str) -> requests.Session:
    """Always create a fresh session with the given key — no global cache."""
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {api_key}"})
    return s


def get_game_id(app_id: str, api_key: str) -> Optional[str]:
    """Get SteamGridDB game ID from a Steam AppID."""
    try:
        s = _make_session(api_key)
        resp = s.get(f"{STEAMGRIDDB_BASE}/games/steam/{app_id}", timeout=10)
        data = resp.json()
        if data.get("success") and data.get("data"):
            return str(data["data"]["id"])
        return None
    except Exception:
        return None


def get_game_id_by_name(game_name: str, api_key: str) -> Optional[str]:
    """
    Get SteamGridDB game ID by searching for the game's name.
    Used as a fallback for very new releases that SteamGridDB hasn't yet
    linked to their Steam AppID — the name search index updates faster
    than the AppID-to-game mapping does.
    Returns the first (best-ranked) search result, or None if nothing matches.
    """
    if not game_name:
        return None
    try:
        s = _make_session(api_key)
        resp = s.get(
            f"{STEAMGRIDDB_BASE}/search/autocomplete/{game_name}",
            timeout=10,
        )
        data = resp.json()
        results = data.get("data", [])
        if data.get("success") and results:
            return str(results[0]["id"])
        return None
    except Exception:
        return None


def download_cover(app_id: str, api_key: str, game_name: str = "") -> Optional[str]:
    """
    Download the best vertical cover (600x900) for a game.
    Falls back to Steam CDN if SteamGridDB fails or key is missing.
    Returns the local file path, or None on complete failure.
    """
    # Always try Steam CDN fallback first if no API key
    if not api_key or api_key.strip() == "YOUR_STEAMGRIDDB_API_KEY":
        return _fallback_steam_header(app_id)

    try:
        sgdb_id = get_game_id(app_id, api_key)

        # Fallback: new releases often aren't linked to their Steam AppID yet
        # on SteamGridDB, even though a name-matched entry already exists.
        if not sgdb_id and game_name:
            sgdb_id = get_game_id_by_name(game_name, api_key)

        if not sgdb_id:
            return _fallback_steam_header(app_id)

        s = _make_session(api_key)
        resp = s.get(
            f"{STEAMGRIDDB_BASE}/grids/game/{sgdb_id}",
            params={"dimensions": "600x900", "limit": 5},
            timeout=10,
        )
        data = resp.json()
        grids = data.get("data", [])
        if not grids:
            return _fallback_steam_header(app_id)

        # Prefer most upvoted
        best = sorted(grids, key=lambda g: g.get("upvotes", 0), reverse=True)[0]
        image_url = best["url"]

        save_path = COVERS_DIR / f"{app_id}.jpg"
        img_resp = requests.get(image_url, timeout=15)
        img_resp.raise_for_status()
        save_path.write_bytes(img_resp.content)
        return str(save_path)

    except Exception:
        return _fallback_steam_header(app_id)


def _fallback_steam_header(app_id: str) -> Optional[str]:
    """
    Fall back to Steam's own vertical library image.
    Steam CDN serves these without authentication.
    """
    urls_to_try = [
        f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg",
        f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_600x900_2x.jpg",
        f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg",
    ]
    save_path = COVERS_DIR / f"{app_id}.jpg"
    for url in urls_to_try:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                save_path.write_bytes(resp.content)
                return str(save_path)
        except Exception:
            continue
    return None


def cover_exists(app_id: str) -> Optional[str]:
    """Return local cover path if already downloaded."""
    path = COVERS_DIR / f"{app_id}.jpg"
    return str(path) if path.exists() else None


def download_all_missing(
    games: list,
    api_key: str,
    on_progress: callable = None,
    on_done: callable = None,
    max_workers: int = 4,
):
    """
    Download covers for all games that don't have one yet.
    Runs in a thread pool — non-blocking.

    Args:
        games:       list of Game objects
        api_key:     SteamGridDB key (can be empty — falls back to Steam CDN)
        on_progress: callback(current: int, total: int, game_name: str)
        on_done:     callback(downloaded: int, failed: int)
        max_workers: parallel download threads (default 4)
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import data.repository as repo

    missing = [g for g in games if not cover_exists(g.app_id)]
    total   = len(missing)

    if total == 0:
        if on_done:
            on_done(0, 0)
        return

    counter    = [0]     # downloaded
    failed_c   = [0]     # failed
    to_save    = []      # games whose cover_path changed — written once at the end
    lock       = threading.Lock()

    def _download_one(game):
        # Network/disk-image-write only — never touches the repository.
        # Batching the repo write at the end (see _run below) avoids
        # serializing every game's save behind the same lock, which
        # throttled throughput to roughly one disk write at a time even
        # though downloads themselves ran in parallel.
        path = None
        try:
            path = download_cover(game.app_id, api_key, game.name)
        except Exception:
            path = None

        with lock:
            counter[0] += 1
            if path:
                game.cover_path = path
                to_save.append(game)
            else:
                failed_c[0] += 1
            current = counter[0]

        if on_progress:
            try:
                on_progress(current, total, game.name)
            except Exception:
                pass
        return path

    def _run():
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_download_one, g): g for g in missing}
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    with lock:
                        failed_c[0] += 1

        # Single write pass for every game whose cover actually downloaded.
        downloaded_count = 0
        if to_save:
            try:
                downloaded_count = repo.update_many(to_save)
            except Exception as e:
                print(f"[SteamGridDB] download_all_missing: update_many failed: {e}")
                with lock:
                    failed_c[0] += len(to_save)
                downloaded_count = 0

        if on_done:
            on_done(downloaded_count, failed_c[0])

    threading.Thread(target=_run, daemon=True).start()