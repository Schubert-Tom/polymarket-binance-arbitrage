from __future__ import annotations
from typing import Optional, Tuple, Union, Any

from datetime import datetime
import re
# - own - #
from tradesystem.domain.market import FutureMarket, FutureType
from tradesystem.domain.currencies import CurrencyType
from tradesystem.domain.order_book import OrderBook
from tradesystem.adapters.clients.binance_options_market_api import BinanceEOptionsClient  

class BinanceBTCUSDFuturePut(FutureMarket):
    api = BinanceEOptionsClient()

    def __init__(self, symbol: str, closingDate: datetime, strike: float, currency: CurrencyType):
        # We use one whole bitcoin as currency since one contract covers one bitcoin --> TODO: Make it available for many currencies (ETH)
        super().__init__("Binance BTC/USD Future Put", FutureType.PUT, currency, strike, closingDate)

        self.symbol = symbol

    def _fetch_order_book_and_update(self):
        books = next(iter(self.api.depths([self.symbol]).values()))
        # print(books)
        self.orderBook.updateData({"bids": books['bids'], "asks": books['asks']})

    def createOrderBook(self):
        """
        Binance Future products have min contract of 0.01
        """
        return OrderBook(self._currency, 0.01, 0.01)

    @classmethod
    def get_all_available_put_options_for_filters(cls,
        *,
        currency: CurrencyType,
        strike_range: Optional[Tuple[float, float]] = None,
        closing_time_range: Optional[Tuple[datetime, datetime]] = None
    ) -> list[BinanceBTCUSDFuturePut]:

        if currency == CurrencyType.BTC:
            underlying = "BTCUSDT"
        elif currency == CurrencyType.ETH:
            underlying = "ETHUSDT"
        else:
            raise ValueError(f"Unsupported currency: {currency}")

        timeRange = [dt.strftime("%Y-%m-%d") for dt in closing_time_range] if closing_time_range else None
        symbols = cls.api.option_symbols(underlying=underlying, side="PUT", strike_range=strike_range, expiry_ms_range=timeRange)
        strikes = [extract_strike_binance(symbol) for symbol in symbols]
        return [cls(closingDate=expiry_from_symbol(symbol), symbol=symbol, strike=strike, currency=currency) for symbol, strike in zip(symbols, strikes)]


def extract_strike_binance(symbol: str) -> float:
    """
    Extract strike price from a Binance option symbol like 'BTC-251226-100000-P'.
    Returns as float.
    """
    try:
        # Format: UNDERLYING-YYMMDD-STRIKE-SIDE
        parts = symbol.split("-")
        if len(parts) < 4:
            raise ValueError(f"Unexpected symbol format: {symbol}")
        return float(parts[2])
    except Exception:
        return float("nan")

_SYMBOL_RE = re.compile(r'^(?P<underlying>[A-Z0-9]+)-(?P<yymmdd>\d{6})-(?P<strike>\d+)-(?P<pc>[PC])$')
def expiry_from_symbol(symbol: str, *, tzinfo: Optional[object] = None) -> datetime:
    """
    Parse symbols like 'BTC-251226-100000-P' -> datetime(2025, 12, 26, 00:00:00 [, tzinfo]).
    Expects format: UNDERLYING-YYMMDD-STRIKE-(P|C)
    """
    m = _SYMBOL_RE.fullmatch(symbol.strip())
    if not m:
        raise ValueError(f"Bad symbol format: {symbol!r} (expected UNDERLYING-YYMMDD-STRIKE-P/C)")
    dt = datetime.strptime(m.group('yymmdd'), '%y%m%d')  # handles 2-digit year
    return dt if tzinfo is None else dt.replace(tzinfo=tzinfo)