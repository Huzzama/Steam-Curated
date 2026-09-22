"""
Fold locales/overlay/*.<loc>.json into locales/<loc>.json and back-fill every
other locale with the English text for keys it lacks (so no screen ever shows
a raw key). Run:  python3 tools/merge_locales.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOC = ROOT / "locales"
OVERLAY = LOC / "overlay"


def deep_merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v


def fill_missing(dst: dict, ref: dict) -> int:
    n = 0
    for k, v in ref.items():
        if isinstance(v, dict):
            if not isinstance(dst.get(k), dict):
                dst[k] = {}
            n += fill_missing(dst[k], v)
        elif k not in dst:
            dst[k] = v
            n += 1
    return n


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def save(p: Path, d: dict) -> None:
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    files = {p.stem: p for p in LOC.glob("*.json")}
    data = {k: load(p) for k, p in files.items()}
    if OVERLAY.is_dir():
        for f in sorted(OVERLAY.glob("*.json")):
            name, loc = f.stem.rsplit(".", 1)
            if loc in data:
                deep_merge(data[loc], load(f))
                print(f"merged {f.name} → {loc}.json")
    en = data["en"]
    for loc, d in data.items():
        if loc == "en":
            continue
        n = fill_missing(d, en)
        if n:
            print(f"{loc}: {n} keys back-filled from en")
    for loc, d in data.items():
        save(files[loc], d)
    if "--keep" not in sys.argv and OVERLAY.is_dir():
        for f in OVERLAY.glob("*.json"):
            f.unlink()
        print("overlays removed")


if __name__ == "__main__":
    main()
