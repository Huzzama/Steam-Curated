import re
import time
import requests
from typing import Optional
from data.models import PriceHistory

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

# Rate limiting: 1 request every 3 seconds
_last_request = 0.0


def _throttle():
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < 3:
        time.sleep(3 - elapsed)
    _last_request = time.time()


def get_price_history(app_id: str, currency: str = "MXN") -> Optional[PriceHistory]:
    """
    Scrape SteamDB for all-time low price data.
    Returns None if unavailable or blocked.
    """
    _throttle()
    try:
        resp = _SESSION.get(
            f"https://steamdb.info/app/{app_id}/",
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        html = resp.text
        return _parse_steamdb_html(html)
    except Exception:
        return None


def _parse_steamdb_html(html: str) -> Optional[PriceHistory]:
    """Extract price history data from SteamDB HTML."""
    try:
        # All-time low price (in various formats)
        low_match = re.search(
            r'lowest recorded price.*?(\$[\d,.]+|[\d,.]+\s*MXN|[\d,.]+\s*USD)',
            html, re.IGNORECASE | re.DOTALL
        )
        all_time_low = 0.0
        if low_match:
            price_str = re.sub(r'[^\d.,]', '', low_match.group(1))
            try:
                all_time_low = float(price_str.replace(',', '.'))
            except ValueError:
                pass

        # All-time low date
        date_match = re.search(
            r'lowest recorded price.*?(\d{1,2}\s+\w+\s+\d{4})',
            html, re.IGNORECASE | re.DOTALL
        )
        low_date = date_match.group(1) if date_match else None

        # Max discount
        discount_match = re.search(r'-(\d+)%.*?lowest', html, re.IGNORECASE)
        max_discount = int(discount_match.group(1)) if discount_match else 0

        return PriceHistory(
            all_time_low=all_time_low,
            all_time_low_date=low_date,
            all_time_discount=max_discount,
            last_sale_price=None,
            last_sale_date=None,
        )
    except Exception:
        return None


def get_price_history_itad(app_id: str) -> Optional[PriceHistory]:
    """
    Alternative: use IsThereAnyDeal API (free, no scraping needed).
    Requires registration at isthereanydeal.com for an API key.
    """
    # Placeholder for ITAD integration
    # GET https://api.isthereanydeal.com/games/storelow/v2
    # ?key={key}&shops=steam&country=MX&appids={app_id}
    return None
