import requests
from tradesystem.domain.market import SpotMarket
from tradesystem.domain.currencies import CurrencyType
from tradesystem.domain.order_book import OrderBook
from cachetools import TTLCache, cached
from tradesystem.adapters.clients.binance_spot_market_api import BinanceSpotClient


class BinanceETHUSDSpot(SpotMarket):
    api = BinanceSpotClient()
    def __init__(self, symbol: str = "ETHUSDT"):
        super().__init__(f"Binance {symbol}", currency=CurrencyType.BTC)
        self.symbol = symbol

    def _fetch_order_book_and_update(self) -> OrderBook:
        books = next(iter(self.api.depths([self.symbol]).values()))
        # print(books)
        self.orderBook.updateData({"bids": books['bids'], "asks": books['asks']})


    def createOrderBook(self) -> OrderBook:
        return OrderBook(self._currency, 0.01, 0.01)
