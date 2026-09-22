import json
import re
from pathlib import Path

LOC = Path(__file__).resolve().parent.parent / "locales"
GLYPH = re.compile(r"[\U0001F000-\U0001FFFF☀-➿←-⇿■-◿⬀-⯿]")


def _flatten(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _flatten(v, prefix + k + ".")
        else:
            yield prefix + k, v


def test_every_locale_has_every_english_key():
    en = dict(_flatten(json.loads((LOC / "en.json").read_text(encoding="utf-8"))))
    for f in LOC.glob("*.json"):
        d = dict(_flatten(json.loads(f.read_text(encoding="utf-8"))))
        missing = set(en) - set(d)
        assert not missing, f"{f.name} missing {sorted(missing)[:5]}"


def test_no_emoji_or_glyph_icons():
    for f in LOC.glob("*.json"):
        for key, val in _flatten(json.loads(f.read_text(encoding="utf-8"))):
            assert not GLYPH.search(str(val)), f"{f.name}:{key} = {val!r}"


def test_format_placeholders_match_english():
    en = dict(_flatten(json.loads((LOC / "en.json").read_text(encoding="utf-8"))))
    ph = re.compile(r"\{(\w+)\}")
    for f in LOC.glob("*.json"):
        for key, val in _flatten(json.loads(f.read_text(encoding="utf-8"))):
            if key in en and isinstance(val, str):
                assert set(ph.findall(val)) <= set(ph.findall(en[key])) | set(), f"{f.name}:{key}"
