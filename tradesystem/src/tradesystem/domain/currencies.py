import enum
from functools import total_ordering

class CurrencyType(enum.Enum):
    BTC = "BTC"
    ETH = "ETH"
    USD = "USDT"
    BNB = "BNB"

@total_ordering
class Currency:
    def __init__(self, currency_type, amount: float):
        self.currency_type = currency_type
        self.amount = amount

    def __repr__(self):
        return f"<Currency(type={self.currency_type}, amount={self.amount})>"

    def _check_comparable(self, other):
        if not isinstance(other, Currency):
            return NotImplemented
        if self.currency_type != other.currency_type:
            raise TypeError(
                f"Cannot compare {self.currency_type} to {other.currency_type}."
            )
        return other

    def __eq__(self, other):
        other = self._check_comparable(other)
        if other is NotImplemented:
            return NotImplemented
        return self.amount == other.amount

    def __lt__(self, other):
        other = self._check_comparable(other)
        if other is NotImplemented:
            return NotImplemented
        return self.amount < other.amount
