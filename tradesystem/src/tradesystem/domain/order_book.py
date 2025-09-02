from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any
from decimal import Decimal, getcontext
import json
import os

# Optional: increase precision a bit for safer cumulative sums
getcontext().prec = 28

class OrderBook:
    """
    Simple OrderBook all quantities are in USD
    """

    def __init__(self, quantity_currency, qty_step_size:float, min_qty_to_purchase: float):
        self.quantity_currency = quantity_currency
        self.qty_step_size = qty_step_size
        self.min_qty_to_purchase = min_qty_to_purchase

    def updateData(self, data: Dict[str, Any], qty_step_size: float = None, min_qty_to_purchase: float = None):
        # Binance returns price/qty as strings, convert to floats
        self.bids: List[Tuple[float, float]] = sorted(
            [(float(p), float(q)) for p, q in data.get("bids", [])],
            key=lambda x: -x[0]  # highest first
        )
        self.asks: List[Tuple[float, float]] = sorted(
            [(float(p), float(q)) for p, q in data.get("asks", [])],
            key=lambda x: x[0]   # lowest first
        )
        if qty_step_size is not None:
            self.qty_step_size = qty_step_size

        if min_qty_to_purchase is not None:
            self.min_qty_to_purchase = min_qty_to_purchase

    def best_bid(self) -> Optional[Tuple[float, float]]:
        """Return (price, qty) of best bid or None if empty."""
        return self.bids[0] if self.bids else None

    def best_ask(self) -> Optional[Tuple[float, float]]:
        """Return (price, qty) of best ask or None if empty."""
        return self.asks[0] if self.asks else None

    def mid_price(self) -> Optional[float]:
        """Return mid price between best bid and best ask, or None if not available."""
        bid, ask = self.best_bid(), self.best_ask()
        if bid and ask:
            return (bid[0] + ask[0]) / 2
        return None

    def spread(self) -> Optional[float]:
        """Return ask - bid spread, or None if not available."""
        bid, ask = self.best_bid(), self.best_ask()
        if bid and ask:
            return ask[0] - bid[0]
        return None

    def bid(self, i: int) -> Optional[Tuple[float, float]]:
        return self.bids[i] if 0 <= i < len(self.bids) else None

    def ask(self, i: int) -> Optional[Tuple[float, float]]:
        return self.asks[i] if 0 <= i < len(self.asks) else None

    def calculate_instant_buy_price_and_size(
        self,
        amount_of_money: float,
        order_type: str = "FOK",  # "FAK" (partial allowed) or "FOK" (all-or-nothing for the given cash)
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Consume the ask side from best to worst to see how much you can buy
        with `amount_of_money`. Returns (avg_price, filled_size) or (None, None)
        if nothing can be filled—or if FOK and not fully fillable.

        amount_of_money: cash budget in quote currency (e.g., USDT).
        order_type:
          - "FAK": partial allowed (IOC / fill-and-kill). Returns whatever can be filled.
          - "FOK": all-or-nothing w.r.t. the cash budget: if any money remains,
                   we return (None, None).
        """
        if amount_of_money is None:
            return None, None
        try:
            remaining = Decimal(str(amount_of_money))
        except Exception:
            return None, None

        if remaining <= 0 or not self.asks:
            return None, None

        total_cost = Decimal("0")
        total_size = Decimal("0")

        # self.asks already sorted from lowest price to highest
        for price_f, size_f in self.asks:
            price = Decimal(str(price_f))
            size_avail = Decimal(str(size_f))

            level_cost = size_avail * price
            take_cost = min(remaining, level_cost)

            if take_cost > 0:
                total_cost += take_cost
                # size taken at this level = cost / price
                total_size += (take_cost / price)
                remaining -= take_cost

            if remaining <= 0:
                break

        # FOK: if we couldn't spend the full budget, consider it unfilled
        if order_type.upper() == "FOK" and remaining > 0:
            return None, None

        if total_size == 0:
            return None, None

        avg_price = (total_cost / total_size)
        return float(avg_price), float(total_size)

    def __repr__(self):
        return (f"<OrderBook {self.symbol} | "
                f"bid={self.best_bid()} ask={self.best_ask()} spread={self.spread()}>")


    def to_json(self):
        return {
            "bids": self.bids,
            "asks": self.asks,
            "qty_step_size": self.qty_step_size,
            "min_qty_to_purchase": self.min_qty_to_purchase,
        }
    
    def save_order_book(self, prefix, dir):
        with open(os.path.join(dir, f"{prefix}_order_book.json"), "w") as f:
            json.dump(self.to_json(), f)