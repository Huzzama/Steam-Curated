import i18n
from ui.format import money, pct, discount, day, compact, compact_money


def setup_module():
    i18n.load_locale("en")


def test_money_symbols():
    assert money(19.99, "USD") == "$19.99"
    assert money(199.5, "MXN") == "MX$199.50"
    assert money(1234, "JPY") == "¥1,234"
    assert money(12.5, "PLN") == "12.50 zł"
    assert money(None) == "—"
    assert money(-3, "USD") == "-$3.00"
    assert money(3, "USD", sign=True) == "+$3.00"


def test_pct_and_discount():
    assert pct(35.4) == "35%"
    assert pct(-12.4, sign=True) == "-12%"
    assert discount(40) == "-40%"
    assert discount(0) == "—"


def test_day_uses_locale_months():
    assert day("2026-06-25") == "25 Jun 2026"
    i18n.load_locale("es")
    assert day("2026-06-25").startswith("25 Jun")  # es: "Junio" → "Jun"
    i18n.load_locale("en")
    assert day(None) == "—"


def test_compact():
    assert compact(999) == "999"
    assert compact(1234) == "1.2K"
    assert compact(1_500_000) == "1.5M"
    assert compact_money(12700.5, "MXN") == "MX$12.7K"
    assert compact_money(99, "USD") == "$99.00"
