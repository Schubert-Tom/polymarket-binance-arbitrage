
from abc import ABC, abstractmethod
import enum
from typing import final

from datetime import datetime
from cachetools import TTLCache, cached

# - own - #
from .order_book import OrderBook
from .currencies import CurrencyType

class MarketInterface(ABC):
    """
    All prices are given in USD
    """
    def __init__(self, name: str, currency: CurrencyType):
        self.name = name
        self._currency = currency
        self.orderBook = self.createOrderBook()

    def __repr__(self):
        return f"{self.name}, \ncurrency={self._currency.value}"

    @final
    @cached(cache=TTLCache(maxsize=50, ttl=2))
    def get_order_book(self) -> OrderBook:
        """
        template method which updates the orderbook
        """
        self._fetch_order_book_and_update()
        return self.orderBook

    @abstractmethod
    def createOrderBook(self) -> OrderBook:
        raise NotImplementedError("Subclasses must implement this method")


    @abstractmethod
    def _fetch_order_book_and_update(self) -> dict:
        raise NotImplementedError("Subclasses must implement this method")

    @final
    def get_underlying_currency(self) -> CurrencyType:
        return self._currency

    ## -- convienent methods
    @final
    def get_best_ask_price(self) -> float:
        """
        Get the best ask price from the order book.
        """
        order_book = self.get_order_book()
        return order_book.best_ask()[0]
    @final
    def get_best_bid_price(self) -> float:
        """
        Get the best bid price from the order book.
        """
        order_book = self.get_order_book()
        return order_book.best_bid()[0]
    
    @final
    def get_price_and_shares_for_instant_buy(self, amount_of_money: float, order_type: str = "FOK") -> tuple[float, float]:
        """
        Get the price and shares for an instant buy order.
        """
        order_book = self.get_order_book()
        return order_book.calculate_instant_buy_price_and_size(amount_of_money, order_type)

    def get_price_for_instant_buy_shares(self, shares: float) -> float:
        """
        Get the price for an instant buy order based on the number of shares.
        """
        order_book = self.get_order_book()
        return order_book.get_price_for_instant_buy_shares(shares)

class FutureType(enum.Enum):
    CALL = "CALL"
    PUT = "PUT"

class FutureMarket(MarketInterface):
    """
    Represents a futures market.
    """
    def __init__(self, name: str, type: FutureType, currency: CurrencyType, strike: float, expirationDate: datetime):
        super().__init__(name, currency)
        self.type = type
        self.strike = strike
        self.expirationDate = expirationDate

    @final
    def get_type(self) -> FutureType:
        return self.type

    @final
    def get_strike_price(self) -> float:
        return self.strike

    @final
    def get_expiration_date(self) -> datetime:
        return self.expirationDate
    
    def __repr__(self):
        return f"{self.name}, \ntype={self.type.value}, \ncurrency={self._currency.value}, \nstrike={self.strike}, \nexpirationDate={self.expirationDate}"

class SpotMarket(MarketInterface):
    """
    Represents a spot market.
    """
    def __init__(self, name: str, currency: CurrencyType):
        super().__init__(name, currency)


class BetOutcome(enum.Enum):
    YES = "YES"
    NO = "NO"

class BetMarket(MarketInterface):
    """
    Represents a bet market.
    """
    def __init__(self, name: str, type: BetOutcome, currency: CurrencyType, strike: float, expirationDate: datetime):
        super().__init__(name, currency)
        
        self.type = type
        self.strike = float(strike)
        self.expirationDate = expirationDate

    @final
    def get_strike_price(self) -> float:
        return self.strike

    @final
    def get_expiration_date(self) -> datetime:
        return self.expirationDate

    @final
    def get_type(self) -> BetOutcome:
        return self.type

