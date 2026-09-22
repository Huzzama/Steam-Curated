"""
Display formatting shared by every view — so no view ever hard-codes "$".
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import i18n

_SYMBOL = {
    "USD": "$", "MXN": "MX$", "EUR": "€", "GBP": "£", "BRL": "R$", "ARS": "AR$",
    "CLP": "CLP$", "COP": "COP$", "PEN": "S/", "CAD": "CA$", "AUD": "A$", "NZD": "NZ$",
    "JPY": "¥", "CNY": "¥", "KRW": "₩", "INR": "₹", "RUB": "₽", "UAH": "₴", "TRY": "₺",
    "PLN": "zł", "CZK": "Kč", "HUF": "Ft", "SEK": "kr", "NOK": "kr", "DKK": "kr",
    "CHF": "CHF", "ZAR": "R", "THB": "฿", "VND": "₫", "IDR": "Rp", "PHP": "₱",
    "SGD": "S$", "HKD": "HK$", "TWD": "NT$", "MYR": "RM", "ILS": "₪", "SAR": "SR",
    "AED": "AED", "KZT": "₸", "QAR": "QR", "KWD": "KD", "CRC": "₡", "UYU": "$U",
}
_NO_DECIMALS = {"JPY", "KRW", "IDR", "VND", "CLP", "COP", "HUF", "TWD"}
_SUFFIX = {"PLN", "CZK", "HUF", "SEK", "NOK", "DKK", "CHF", "AED", "KZT"}


def money(amount: Optional[float], currency: str = "USD", *, sign: bool = False) -> str:
    """money(19.99, 'MXN') → 'MX$19.99'   money(None) → '—'"""
    if amount is None:
        return "—"
    cur = (currency or "USD").upper()
    sym = _SYMBOL.get(cur, cur + " ")
    decimals = 0 if cur in _NO_DECIMALS else 2
    num = f"{abs(amount):,.{decimals}f}"
    body = f"{num} {sym}" if cur in _SUFFIX else f"{sym}{num}"
    if amount < 0:
        return "-" + body
    return ("+" + body) if sign and amount > 0 else body


def pct(value: Optional[float], *, sign: bool = False) -> str:
    """pct(35) → '35%'  pct(-12.4, sign=True) → '-12%'"""
    if value is None:
        return "—"
    v = round(value)
    return f"{'+' if sign and v > 0 else ''}{v}%"


def discount(value: Optional[int]) -> str:
    """discount(35) → '-35%'"""
    return "—" if not value else f"-{int(value)}%"


def day(value: Optional[str | date | datetime], fmt: str = "{d} {mon} {y}") -> str:
    """ISO string / date → '25 Jun 2026' with the month name from the locale
    (`months.<n>`, first three letters). {d} {mon} {month} {y} placeholders."""
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value[:19])
        except ValueError:
            return value
    month = i18n.t(f"months.{value.month}")
    if month.startswith("months."):
        month = value.strftime("%B")
    return fmt.format(d=f"{value.day:02d}", mon=month[:3], month=month, y=value.year)


def count(n: int, singular_key: str, plural_key: str) -> str:
    """Localized '1 game' / '12 games' from two i18n keys with {n}."""
    return i18n.t(singular_key if n == 1 else plural_key, n=n)


def compact(n: float) -> str:
    """1234 → '1.2K', 1_500_000 → '1.5M'"""
    n = float(n)
    for unit, div in (("M", 1_000_000), ("K", 1_000)):
        if abs(n) >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + unit
    return f"{n:.0f}"


def compact_money(amount: Optional[float], currency: str = "USD") -> str:
    """money() for stat tiles: 12 700.5 → 'MX$12.7K' so the mono value never overflows."""
    if amount is None:
        return "—"
    if abs(amount) < 10_000:
        return money(amount, currency)
    cur = (currency or "USD").upper()
    sym = _SYMBOL.get(cur, cur + " ")
    body = compact(abs(amount))
    body = f"{body} {sym}" if cur in _SUFFIX else f"{sym}{body}"
    return ("-" if amount < 0 else "") + body
