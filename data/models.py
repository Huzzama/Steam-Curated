from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PriceInfo:
    current: float
    base: float
    currency: str
    discount_pct: int
    is_on_sale: bool


@dataclass
class PriceHistory:
    all_time_low: float
    all_time_low_date: Optional[str]
    all_time_discount: int
    last_sale_price: Optional[float]
    last_sale_date: Optional[str]
    source: str = ""          # "itad" | "observed" | "" (unknown / legacy)


@dataclass
class Purchase:
    """Records a confirmed game purchase."""
    app_id:        str
    name:          str
    purchased_at:  str          # ISO date YYYY-MM-DD
    price_paid:    float        # what the user actually paid
    base_price:    float        # full price without discount
    currency:      str
    discount_pct:  int          # % discount at purchase
    edition:       str          # "Standard", "Deluxe", "Ultimate", etc.
    saved:         float        # base_price - price_paid
    kind:          str = "game"                         # game · edition · bundle
    items:         list = field(default_factory=list)  # [{app_id, name}] of an edition / bundle
    verification:  str = ""     # "" never sent · verified · partial · unverified · unknown
    verified_items: list = field(default_factory=list) # [{app_id, state, type}] from the server
    saving_reported: bool = True  # saving already counted on pimpmysteam.com (old versions)


@dataclass
class Game:
    id: int
    name: str
    app_id: str
    steam_url: str
    genre: str
    release_year: int
    developer: str
    publisher: str
    categories: str
    short_description: str
    priority: str          # S, A, B, C
    status: str            # Wishlist, Comprado, Archivado
    price: Optional[PriceInfo] = None
    price_history: Optional[PriceHistory] = None
    personal_rating: Optional[int] = None
    notes: str = ""
    cover_path: Optional[str] = None
    date_added: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    play_status: str = ""   # "", "playing", "completed", "abandoned", "on_hold"

    @property
    def buy_recommendation(self) -> str:
        if not self.price or not self.price_history:
            return "No data"
        if self.price_history.all_time_low <= 0:
            return "No history"
        diff = (self.price.current - self.price_history.all_time_low) / self.price_history.all_time_low
        if diff <= 0.05:
            return "Buy now"
        elif diff <= 0.20:
            return "Near low"
        else:
            return "Wait for sale"

    @property
    def is_at_low(self) -> bool:
        """On sale right now at (or within 5 % of) the lowest price ever recorded.
        A game at full price is never "at its low" — not even one that has
        never been discounted (its "low" would just be the full price)."""
        p, h = self.price, self.price_history
        if not p or not h or not h.all_time_low or h.all_time_low <= 0:
            return False
        if not (p.is_on_sale and (p.discount_pct or 0) > 0):
            return False
        return p.current <= h.all_time_low * 1.05

    @property
    def price_diff_pct(self) -> Optional[float]:
        if not self.price or not self.price_history:
            return None
        if self.price_history.all_time_low <= 0:
            return None
        return ((self.price.current - self.price_history.all_time_low)
                / self.price_history.all_time_low) * 100


@dataclass
class SteamSaleEvent:
    name: str
    start_date: str
    end_date: str
    is_confirmed: bool