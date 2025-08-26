from __future__ import annotations
from typing import *
import enum
import requests
from datetime import datetime
import re

# -own - #
from tradesystem.domain.currencies import CurrencyType
from tradesystem.domain.market import BetOutcome, BetMarket
from tradesystem.domain.order_book import OrderBook


class PolyMarketBet_Crypto_Price_Bet(BetMarket):

    def __init__(self, question, closingDate: datetime, strike:float, glob_token: str, outcome:BetOutcome, orderMinSize: int = 5, orderPriceMinTickSize: float = 0.01):
        assert isinstance(outcome, BetOutcome), "outcome must be an instance of BetOutcome"
        self.closingDate = closingDate
        self.question = question
        self.outcome = outcome
        self.glob_token = glob_token

        self.orderMinSize = orderMinSize # how many quantities need to be bought per purchase
        self.orderPriceMinTickSize = orderPriceMinTickSize # the minimum price increment

        # TODO change to any crypto not just btc
        super().__init__(f"Polymarket: {question}\n --> {outcome.value}", outcome, currency=CurrencyType.USD, strike=strike, expirationDate=closingDate)


    def _fetch_order_book_and_update(self) -> dict:
        response = requests.get(f"https://clob.polymarket.com/book?token_id={self.glob_token}")
        if response.status_code != 200:
            raise Exception("no orderbook")
        data = response.json()
        tick_size = data["tick_size"]
        min_order_size = data["min_order_size"]
        self.orderBook.updateData({"bids": [bid.values() for bid in data["bids"]], "asks": [ask.values() for ask in data["asks"]]}, min_qty_to_purchase=min_order_size, qty_step_size=tick_size)

    def get_outcome(self):
        return self.outcome
    
    def createOrderBook(self):
        return OrderBook(self._currency, self.orderPriceMinTickSize, min_qty_to_purchase=self.orderMinSize)

    @classmethod
    def yes_and_now_from_api_market_dict(cls,
        marketDict: dict,
        ) -> List[BetMarket]:
        globTokens = marketDict["clobTokenIds"] # assume no for now
        assert len(globTokens) == 2, "Expected exactly two clobTokenIds"
        strike = extract_dollar_amount_from_question(marketDict["question"])
        closingDate = getClosingDateMarket(marketDict)

        outcomes = []
        for outcome in marketDict["outcomes"]:
            if BetOutcome.YES.value == outcome.upper():
                outcome = BetOutcome.YES
            elif BetOutcome.NO.value == outcome.upper():
                outcome = BetOutcome.NO
            else:
                raise ValueError(f"Unexpected outcome value: {outcome}")
            outcomes.append(outcome)

        markets = []
        for i in range(2):
            markets.append(cls(question=marketDict["question"], closingDate=closingDate, strike=strike, glob_token=globTokens[i], outcome=outcomes[i]))

        return markets


pattern = re.compile(r"\$([\d.,]+)([KMB]?)", re.IGNORECASE)
def extract_dollar_amount_from_question(question: str) -> int | None:
    m = pattern.search(question)
    if not m:
        return None
    
    number_str, suffix = m.groups()
    number = float(number_str.replace(",", ""))
    
    multiplier = {
        "": 1,
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
    }
    
    return float(number * multiplier[suffix.upper()])


def getClosingDateMarket(market: dict) -> datetime:
    """
    Returns the closing date of the market.
    """
    if 'endDateIso' in market:
        return datetime.fromisoformat(market['endDateIso'])
    elif 'end_date' in market:
        # print(market["end_date"])
        pass
    return None
