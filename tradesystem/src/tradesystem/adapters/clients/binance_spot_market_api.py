import time
import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from tradesystem.domain.order_book import OrderBook  # keep for typing parity with your eOptions client

DateLike = Union[int, float, str, dt.date, dt.datetime, None]


class BinanceSpotClient:
    """
    Minimal, read-only client for Binance Spot (no trading).

    Base URL: https://api.binance.com
    This client ONLY performs GET requests to public endpoints.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://api.binance.com",
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff: float = 0.5,
        max_workers: int = 8,
        user_agent: str = "binance-spot-client/1.0",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.max_workers = max_workers
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent})

    # ---------- low-level helpers ----------

    def _to_epoch_ms(self, x: DateLike) -> Optional[int]:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return int(x if x >= 1e12 else x * 1000)
        if isinstance(x, str):
            d = dt.datetime.strptime(x, "%Y-%m-%d")
            return int(d.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
        if isinstance(x, dt.datetime):
            if x.tzinfo is None:
                x = x.replace(tzinfo=dt.timezone.utc)
            else:
                x = x.astimezone(dt.timezone.utc)
            return int(x.timestamp() * 1000)
        if isinstance(x, dt.date):
            d = dt.datetime(x.year, x.month, x.day, tzinfo=dt.timezone.utc)
            return int(d.timestamp() * 1000)
        return None

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        GET with simple retry on 429/5xx, respecting Retry-After when present.
        """
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            try:
                resp = self.s.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (429, 500, 502, 503, 504):
                    if attempt >= self.max_retries:
                        resp.raise_for_status()
                    attempt += 1
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            time.sleep(float(retry_after))
                        except ValueError:
                            time.sleep(self.backoff * attempt)
                    else:
                        time.sleep(self.backoff * attempt)
                    continue
                resp.raise_for_status()
            except (requests.ConnectionError, requests.Timeout):
                if attempt >= self.max_retries:
                    raise
                attempt += 1
                time.sleep(self.backoff * attempt)

    # ---------- public read-only endpoints ----------

    def exchange_info(self) -> Dict[str, Any]:
        """Raw exchange metadata (symbols, filters, etc.)."""
        return self._get("/api/v3/exchangeInfo")

    def spot_symbols(
        self,
        *,
        base: Optional[Union[str, Iterable[str]]] = None,   # e.g. "BTC" or ["BTC","ETH"]
        quote: Optional[str] = None,                         # e.g. "USDT"
        status: Optional[str] = "TRADING",                   # filter tradable by default
        return_symbols_only: bool = True,
    ) -> List[Union[str, Dict[str, Any]]]:
        """
        List spot symbols with optional filtering.
        """
        info = self.exchange_info()
        bases: Optional[set] = None
        if base is not None:
            if isinstance(base, str):
                bases = {base.upper()}
            else:
                bases = {b.upper() for b in base}

        q = quote.upper() if quote else None

        out: List[Union[str, Dict[str, Any]]] = []
        for row in info.get("symbols", []):
            if status and row.get("status") != status:
                continue
            if bases and row.get("baseAsset") not in bases:
                continue
            if q and row.get("quoteAsset") != q:
                continue
            out.append(row["symbol"] if return_symbols_only else row)

        return sorted(out)

    def depth(self, symbol: str, *, limit: int = 100) -> Dict[str, Any]:
        """
        Order book (raw) for one spot symbol (e.g. 'BTCUSDT').
        Valid limits: 5,10,20,50,100,500,1000
        """
        symbol = symbol.upper()
        return self._get("/api/v3/depth", params={"symbol": symbol, "limit": limit})

    def depths(
        self,
        symbols: Iterable[str],
        *,
        limit: int = 100,
    ) -> Dict[str, Optional[OrderBook]]:
        """
        Order books for many symbols (parallelized).
        Returns {symbol: OrderBook(...) or None}. (Raw dicts if you don't wrap them.)
        """
        sym_list = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
        if not sym_list:
            return {}

        def _one(sym: str) -> Optional[OrderBook]:
            try:
                data = self.depth(sym, limit=limit)
                return data  # keep raw; adapt to your OrderBook downstream if desired
            except Exception:
                return None

        results: Dict[str, Optional[OrderBook]] = {s: None for s in sym_list}
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futs = {ex.submit(_one, s): s for s in sym_list}
            for fut in as_completed(futs):
                s = futs[fut]
                try:
                    results[s] = fut.result()
                except Exception:
                    results[s] = None
        return results

    def recent_trades(self, symbol: str, *, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Most recent trades (public).
        """
        symbol = symbol.upper()
        return self._get("/api/v3/trades", params={"symbol": symbol, "limit": limit})

    def agg_trades(
        self,
        symbol: str,
        *,
        from_id: Optional[int] = None,
        start_time: DateLike = None,
        end_time: DateLike = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        Compressed/Aggregate trades.
        """
        symbol = symbol.upper()
        params: Dict[str, Any] = {"symbol": symbol, "limit": limit}
        if from_id is not None:
            params["fromId"] = int(from_id)
        st = self._to_epoch_ms(start_time)
        et = self._to_epoch_ms(end_time)
        if st is not None:
            params["startTime"] = st
        if et is not None:
            params["endTime"] = et
        return self._get("/api/v3/aggTrades", params=params)

    def klines(
        self,
        symbol: str,
        *,
        interval: str = "1m",
        start_time: DateLike = None,
        end_time: DateLike = None,
        limit: int = 500,
    ) -> List[List[Any]]:
        """
        Klines/candlesticks. Returns raw kline arrays per Binance spec.
        """
        symbol = symbol.upper()
        params: Dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        st = self._to_epoch_ms(start_time)
        et = self._to_epoch_ms(end_time)
        if st is not None:
            params["startTime"] = st
        if et is not None:
            params["endTime"] = et
        return self._get("/api/v3/klines", params=params)

    def avg_price(self, symbol: str) -> Dict[str, Any]:
        """
        Current average price for a symbol.
        """
        symbol = symbol.upper()
        return self._get("/api/v3/avgPrice", params={"symbol": symbol})

    def ticker_price(self, symbol: Optional[str] = None) -> Any:
        """
        Latest price(s).
        - If `symbol` is provided, returns {'symbol': 'BTCUSDT', 'price': '...'}
        - Else returns list for all symbols.
        """
        params = {"symbol": symbol.upper()} if symbol else None
        return self._get("/api/v3/ticker/price", params=params)

    def prices(self, symbols: Optional[Iterable[str]] = None) -> Dict[str, float]:
        """
        Convenience: returns {symbol: price_float}. If `symbols` is None, returns all.
        """
        data = self.ticker_price(symbol=None)
        all_prices = {row["symbol"]: float(row["price"]) for row in data}
        if symbols is None:
            return all_prices
        wanted = {s.strip().upper() for s in symbols if s and s.strip()}
        return {s: p for s, p in all_prices.items() if s in wanted}

    def book_ticker(self, symbol: Optional[str] = None) -> Any:
        """
        Best bid/ask (top of book).
        - If `symbol` is provided, returns one object.
        - Else returns list for all symbols.
        """
        params = {"symbol": symbol.upper()} if symbol else None
        return self._get("/api/v3/ticker/bookTicker", params=params)

    def book_tickers(self, symbols: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, float]]:
        """
        Convenience: returns {symbol: {'bidPrice': ..., 'bidQty': ..., 'askPrice': ..., 'askQty': ...}}.
        If `symbols` is provided, filters to that set.
        """
        data = self.book_ticker(symbol=None)
        def _row_to_map(row: Dict[str, Any]) -> Dict[str, float]:
            return {
                "bidPrice": float(row["bidPrice"]),
                "bidQty": float(row["bidQty"]),
                "askPrice": float(row["askPrice"]),
                "askQty": float(row["askQty"]),
            }
        all_map = {row["symbol"]: _row_to_map(row) for row in data}
        if symbols is None:
            return all_map
        wanted = {s.strip().upper() for s in symbols if s and s.strip()}
        return {s: v for s, v in all_map.items() if s in wanted}

    def stats_24hr(self, symbol: Optional[str] = None) -> Any:
        """
        24hr rolling window price change statistics.
        - If `symbol` is provided, returns one object.
        - Else returns list for all symbols.
        """
        params = {"symbol": symbol.upper()} if symbol else None
        return self._get("/api/v3/ticker/24hr", params=params)

    # ---------- convenience wrappers tailored to BTC/ETH on USDT ----------

    def btc_usdt_orderbook(self, *, limit: int = 100) -> Dict[str, Any]:
        """Order book for BTCUSDT."""
        return self.depth("BTCUSDT", limit=limit)

    def eth_usdt_orderbook(self, *, limit: int = 100) -> Dict[str, Any]:
        """Order book for ETHUSDT."""
        return self.depth("ETHUSDT", limit=limit)

    def btc_eth_symbols_usdt(
        self,
        *,
        symbols_only: bool = True,
    ) -> List[Union[str, Dict[str, Any]]]:
        """Shortcut: BTC/ETH quoted in USDT and trading."""
        return self.spot_symbols(base=["BTC", "ETH"], quote="USDT", status="TRADING", return_symbols_only=symbols_only)

    def btc_eth_book_tickers(self) -> Dict[str, Dict[str, float]]:
        """Top of book for BTCUSDT and ETHUSDT."""
        return self.book_tickers(symbols=["BTCUSDT", "ETHUSDT"])

    def btc_eth_prices(self) -> Dict[str, float]:
        """Latest prices for BTCUSDT and ETHUSDT."""
        return self.prices(symbols=["BTCUSDT", "ETHUSDT"])
