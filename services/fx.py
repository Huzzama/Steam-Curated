"""
Exchange rates for the region price comparison ("35 % cheaper than your region").

Rates come from ExchangeRate-API's free open endpoint (no key, updated daily)
and are cached for 12 h in <BASE_DIR>/fx_rates.json. Offline, the last cached
rates are used; with no cache at all, a rough built-in table keeps the
comparison working (marked source "builtin").

    rates()                       → ({"USD": 1.0, "MXN": 18.4, …} units per USD, meta)
    convert(amount, frm, to)      → float | None
    meta: {"source": "live" | "cached" | "builtin", "date": "2026-09-28" | None}

Blocking on the first call of the day — call it from a worker thread.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("curator.fx")

URL = "https://open.er-api.com/v6/latest/USD"
ATTRIBUTION_URL = "https://www.exchangerate-api.com"
TTL_S = 12 * 3600

# Rough USD value of one unit — last-resort fallback only.
_BUILTIN_USD_PER_UNIT = {
    "USD": 1.0, "MXN": 0.050, "BRL": 0.18, "JPY": 0.0065, "EUR": 1.08, "GBP": 1.27,
    "CAD": 0.73, "AUD": 0.64, "RUB": 0.011, "TRY": 0.028, "KRW": 0.00073, "CNY": 0.138,
    "PLN": 0.25, "CZK": 0.044, "HUF": 0.0027, "NOK": 0.094, "SEK": 0.095, "DKK": 0.145,
    "CHF": 1.12, "NZD": 0.60, "SGD": 0.74, "HKD": 0.128, "TWD": 0.031, "THB": 0.028,
    "INR": 0.012, "CLP": 0.00105, "COP": 0.00024, "PEN": 0.27, "ARS": 0.00095, "UAH": 0.024,
    "KZT": 0.0020, "IDR": 0.000062, "MYR": 0.22, "PHP": 0.017, "VND": 0.000039,
    "ZAR": 0.055, "SAR": 0.27, "AED": 0.27, "ILS": 0.27, "QAR": 0.27, "KWD": 3.25,
    "CRC": 0.0019, "UYU": 0.024,
}
BUILTIN = {k: 1.0 / v for k, v in _BUILTIN_USD_PER_UNIT.items()}

_lock = threading.Lock()
_mem: Optional[dict] = None


def _path():
    import config
    return config.BASE_DIR / "fx_rates.json"


def _read_cache() -> Optional[dict]:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(d.get("rates"), dict) and d["rates"].get("USD"):
            return d
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _write_cache(d: dict) -> None:
    path = _path()
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        log.info("fx cache not saved: %s", e)


def _fetch() -> Optional[dict]:
    from services._http import SESSION
    try:
        r = SESSION.get(URL, timeout=8)
        r.raise_for_status()
        j = r.json()
        if j.get("result") != "success" or not isinstance(j.get("rates"), dict):
            return None
        stamp = j.get("time_last_update_unix") or time.time()
        return {"fetched": time.time(),
                "date": datetime.fromtimestamp(stamp, timezone.utc).date().isoformat(),
                "rates": {k.upper(): float(v) for k, v in j["rates"].items() if v}}
    except Exception as e:  # noqa: BLE001 — offline is a normal state
        log.info("fx rates not fetched: %s", e)
        return None


def reset_cache() -> None:
    global _mem
    with _lock:
        _mem = None


def rates(allow_network: bool = True) -> tuple[dict, dict]:
    global _mem
    with _lock:
        d = _mem or _read_cache()
        fresh = bool(d) and time.time() - float(d.get("fetched") or 0) < TTL_S
        if not fresh and allow_network:
            new = _fetch()
            if new:
                d = new
                _write_cache(d)
                _mem = d
                return d["rates"], {"source": "live", "date": d.get("date")}
        if d:
            _mem = d
            return d["rates"], {"source": "cached", "date": d.get("date")}
        return BUILTIN, {"source": "builtin", "date": None}


def convert(amount: Optional[float], frm: str, to: str, table: Optional[dict] = None) -> Optional[float]:
    """*amount* in currency *frm* expressed in *to*; None if either is unknown."""
    if amount is None:
        return None
    frm, to = (frm or "").upper(), (to or "").upper()
    if frm == to:
        return float(amount)
    t = table if table is not None else rates()[0]
    a, b = t.get(frm) or BUILTIN.get(frm), t.get(to) or BUILTIN.get(to)
    if not a or not b:
        return None
    return float(amount) / a * b
