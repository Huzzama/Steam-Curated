"""
"Is there a newer Steam Curator?" — asks GitHub for the latest Release once a
day and remembers the answer in settings. Never blocks: call check() from a
worker thread (ui.async_bridge.run_async).

    check(force=False)  → {"latest": "2.1.0", "url": "…", "newer": True} or None (offline)
    latest_known()      → the cached answer, without touching the network
    is_newer(a, b)      → "2.1.0" > "2.0.0"  (numeric parts, "v" prefix and
                          suffixes like "-beta" tolerated)
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

log = logging.getLogger("curator.update")

CHECK_EVERY_S = 24 * 3600
_KEY_AT, _KEY_LATEST, _KEY_URL = "update_checked_at", "update_latest", "update_url"


def _parts(v: str) -> tuple:
    v = (v or "").strip().lstrip("vV")
    m = re.match(r"(\d+(?:\.\d+)*)", v)
    nums = [int(x) for x in (m.group(1).split(".") if m else [])]
    while len(nums) < 3:
        nums.append(0)
    # a pre-release ("2.1.0-beta") sorts below the final release
    return tuple(nums[:4]) + ((0,) if re.search(r"\d[-+][A-Za-z]", v) else (1,))


def is_newer(candidate: str, current: str) -> bool:
    return _parts(candidate) > _parts(current)


def _release_url() -> str:
    from config import APP_REPO
    return f"https://github.com/{APP_REPO}/releases/latest"


def latest_known() -> Optional[dict]:
    from config import APP_VERSION
    from ui.settings_loader import get_settings
    s = get_settings()
    latest = s.get(_KEY_LATEST)
    if not latest:
        return None
    return {"latest": latest, "url": s.get(_KEY_URL) or _release_url(),
            "newer": is_newer(latest, APP_VERSION)}


def check(force: bool = False) -> Optional[dict]:
    """Blocking (network). Returns the cached answer when it is fresh."""
    from config import APP_REPO, APP_VERSION
    from services._http import SESSION
    from ui.settings_loader import get_settings, save_settings
    s = get_settings()
    if not force and time.time() - float(s.get(_KEY_AT) or 0) < CHECK_EVERY_S and s.get(_KEY_LATEST):
        return latest_known()
    try:
        r = SESSION.get(f"https://api.github.com/repos/{APP_REPO}/releases/latest",
                        headers={"Accept": "application/vnd.github+json"}, timeout=10)
        r.raise_for_status()
        j = r.json()
        latest = str(j.get("tag_name") or "").lstrip("vV")
        url = str(j.get("html_url") or _release_url())
    except Exception as e:  # noqa: BLE001 — offline, rate-limited, no release yet
        log.info("update check skipped: %s", e)
        return None
    if not latest or not url.startswith("https://github.com/"):
        return None
    save_settings({_KEY_AT: time.time(), _KEY_LATEST: latest, _KEY_URL: url})
    return {"latest": latest, "url": url, "newer": is_newer(latest, APP_VERSION)}
