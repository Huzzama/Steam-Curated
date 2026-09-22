"""
Apply a flat translation file to a locale:
    python3 tools/apply_translations.py de /path/to/de.flat.json
The flat file maps dotted keys ("wishlist.empty_title") to translated strings.
Keys unknown to en.json are ignored; placeholders must match the English text.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PH = re.compile(r"\{(\w+)\}")


def flat(d, p=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flat(v, p + k + ".")
        else:
            yield p + k, v


def setk(d, key, val):
    parts = key.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = val


def main(loc: str, src: str) -> None:
    en = dict(flat(json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))))
    target = ROOT / "locales" / f"{loc}.json"
    d = json.loads(target.read_text(encoding="utf-8"))
    tr = json.loads(Path(src).read_text(encoding="utf-8"))
    ok = skipped = 0
    for k, v in tr.items():
        if k not in en or not isinstance(v, str) or not v.strip():
            skipped += 1
            continue
        if set(PH.findall(v)) != set(PH.findall(en[k])):
            print(f"  placeholder mismatch, kept English: {k}")
            skipped += 1
            continue
        setk(d, k, v)
        ok += 1
    target.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{loc}: {ok} applied, {skipped} skipped")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
