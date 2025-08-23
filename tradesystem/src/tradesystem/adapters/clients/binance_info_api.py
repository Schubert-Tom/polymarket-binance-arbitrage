import time
import datetime as dt
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from tradesystem.domain.order_book import OrderBook

DateLike = Union[int, float, str, dt.date, dt.datetime, None]


def _to_epoch_ms(x: DateLike) -> Optional[int]:
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


class BinanceEOptionsClient:
    """
    Minimal, read-only client for Binance eOptions (no trading).

    Base URL: https://eapi.binance.com
    This client ONLY performs GET requests to public endpoints.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://eapi.binance.com",
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff: float = 0.5,
        max_workers: int = 8,
        user_agent: str = "binance-eoptions-client/1.0",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.max_workers = max_workers
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent})

    # ---------- low-level helpers ----------

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
                    # basic backoff; respect Retry-After if sent
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
                # Non-retryable error
                resp.raise_for_status()
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt >= self.max_retries:
                    raise
                attempt += 1
                time.sleep(self.backoff * attempt)

    # ---------- public read-only endpoints ----------

    def exchange_info(self) -> Dict[str, Any]:
        """Raw exchange metadata (symbols, filters, etc.)."""
        return self._get("/eapi/v1/exchangeInfo")

    def option_symbols(
        self,
        *,
        underlying: Optional[str] = None,
        side: Optional[str] = None,  # "CALL" or "PUT"
        strike_range: Optional[Tuple[float, float]] = None,
        expiry_ms_range: Optional[Tuple[DateLike, DateLike]] = None,
        return_symbols_only: bool = True,
    ) -> List[Union[str, Dict[str, Any]]]:
        """
        List option symbols with optional filtering.
        - underlying: e.g. "BTCUSDT"
        - side: "CALL" or "PUT"
        - strike_range: (min, max) inclusive
        - expiry_ms_range: (min, max) in various formats (epoch ms/sec, YYYY-MM-DD, date/datetime)
        """
        info = self.exchange_info()
        min_strike = max_strike = None
        if strike_range:
            min_strike, max_strike = strike_range
            if min_strike > max_strike:
                raise ValueError("strike_range min must be <= max")

        min_exp = max_exp = None
        if expiry_ms_range:
            a, b = expiry_ms_range
            min_exp, max_exp = _to_epoch_ms(a), _to_epoch_ms(b)
            if min_exp and max_exp and min_exp > max_exp:
                raise ValueError("expiry_ms_range min must be <= max")

        out: List[Union[str, Dict[str, Any]]] = []
        for row in info.get("optionSymbols", []):
            if underlying and row.get("underlying") != underlying:
                continue
            if side and row.get("side") != side:
                continue

            strike_val = row.get("strikePrice")
            try:
                strike_f = float(strike_val) if strike_val is not None else None
            except (TypeError, ValueError):
                strike_f = None

            exp_ms = row.get("expiryDate")
            exp_ms = int(exp_ms) if exp_ms is not None else None

            if strike_range and (strike_f is None or strike_f < min_strike or strike_f > max_strike):
                continue
            if expiry_ms_range:
                if (min_exp is not None and (exp_ms is None or exp_ms < min_exp)) or \
                   (max_exp is not None and (exp_ms is None or exp_ms > max_exp)):
                    continue

            out.append(row["symbol"] if return_symbols_only else row)

        # Sort by expiry then strike if fields exist
        def _key(sym_or_row):
            if isinstance(sym_or_row, str):
                # fall back: keep lexicographic
                return sym_or_row
            return (sym_or_row.get("expiryDate", 0), float(sym_or_row.get("strikePrice", 0.0)))

        return sorted(out, key=_key)

    def depth(self, symbol: str, *, limit: int = 100) -> Dict[str, Any]:
        """Order book for one option symbol."""
        return self._get("/eapi/v1/depth", params={"symbol": symbol, "limit": limit})

    def depths(
        self,
        symbols: Iterable[str],
        *,
        limit: int = 10,
    ) -> Dict[str, Optional[OrderBook]]:
        """
        Order books for many symbols (parallelized). 
        Returns {symbol: OrderBook(...) or None}.
        """
        sym_list = list(dict.fromkeys(s.strip() for s in symbols if s and s.strip()))
        if not sym_list:
            return {}

        def _one(sym: str) -> Optional[OrderBook]:
            try:
                data = self.depth(sym, limit=limit)
                return OrderBook(sym, data)
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


    def mark_prices(self, symbol: Optional[str] = None) -> Any:
        """
        Mark price snapshot(s).
        - If `symbol` is provided, returns a single symbol's mark.
        - Else returns a list for all symbols.
        """
        params = {"symbol": symbol} if symbol else None
        return self._get("/eapi/v1/mark", params=params)

    def recent_trades(self, symbol: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """Recent trades for a given option symbol."""
        return self._get("/eapi/v1/trades", params={"symbol": symbol, "limit": limit})

    # ---------- convenience wrappers tailored to BTC PUTs ----------

    def btc_put_symbols(
        self,
        *,
        strike_range: Optional[Tuple[float, float]] = None,
        closing_time_range: Optional[Tuple[DateLike, DateLike]] = None,
        symbols_only: bool = True,
    ) -> List[Union[str, Dict[str, Any]]]:
        """Shortcut to list BTCUSDT PUT options with optional filters."""
        return self.option_symbols(
            underlying="BTCUSDT",
            side="PUT",
            strike_range=strike_range,
            expiry_ms_range=closing_time_range,
            return_symbols_only=symbols_only,
        )

    def btc_put_orderbooks(
        self,
        *,
        strike_range: Optional[Tuple[float, float]] = None,
        closing_time_range: Optional[Tuple[DateLike, DateLike]] = None,
        limit: int = 100,
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        One-call helper: filter BTC PUTs, then fetch their order books.
        """
        symbols = self.btc_put_symbols(
            strike_range=strike_range,
            closing_time_range=closing_time_range,
            symbols_only=True,
        )
        return self.depths(symbols, limit=limit)
