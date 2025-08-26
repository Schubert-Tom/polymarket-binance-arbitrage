import numpy as np
import math

# - own - # 
from tradesystem.domain.market import BetMarket, BetOutcome, SpotMarket, FutureType

class DeltaHedgeStrategy_NoFees:
    """
    This strategy goes long short:
    * Short on Polymarket,
    * Spot on binance,
    * No slippage/fees are assumed for all trades,
    * Binance is assumed to be liquide enough in the spot market price is constant when we buy --> no order book jumps

    This strategy assumes buy and hold and does not react on market movement.
    --> Can lead to losses as we see in calculate_pay_off_curve_buy_and_hold.
    This strategy can be used as a base for more advanced strategies.

    Inputs:
    - gain_when_bet_looses: The minimum gain in dollars when the bet looses (Loosing bet should through increased price of crypto should not lead to loss/no gain)
    - capital_to_invest: the amount of capital to invest in the strategy
    - bitcoin_market: the current state of the bitcoin market
    - polymarket: the current state of the polymarket

    Algorithm:
    We go long on Binance and short on Polymarket.
    We only trade bitcoin on binance and keep the bet on polymarket until the market closes.
    """
    def __init__(self, gain_when_bet_looses:float, capital_to_invest:float, cryptoSpotMarket:SpotMarket, polyMarketBetCryptoPrice:BetMarket):
        self.gain_when_bet_looses = gain_when_bet_looses
        self.capital_to_invest = capital_to_invest

        assert isinstance(cryptoSpotMarket, SpotMarket), "cryptoSpotMarket must be a SpotMarket"
        assert isinstance(polyMarketBetCryptoPrice, BetMarket), "polyMarketBetCryptoPrice must be a BetMarket"
        assert polyMarketBetCryptoPrice.get_type() == BetOutcome.NO, "Betting outcome must be NO so we are in the money below strike"

        self.cryptoSpotMarket = cryptoSpotMarket
        self.polyMarketBetCryptoPrice = polyMarketBetCryptoPrice

    def _calculate_invest_size_for_spot_and_bet(self, spotPrice, strike):
        """
        Calculates the concrete amount of capital to hedge. Considering the invested capital and interest rate in this strategy

        btcPrice: float or np.ndarray of shape (n,)
        upwardslimit: float, the upper bound bitcoin price when the hedge goes to the zero

        return: returns the amount of money which should be used for hedging in this strategy

        """
        assert isinstance(strike, float), "upwardslimit must be a float"
        spot_increase = strike / spotPrice

        minGainRelative = self.gain_when_bet_looses / self.capital_to_invest

        # 1 = spot + bet 
        # spot * r = 1-spot
        # r + 1 = (1 / spot)
        to_be_invested_in_spot = ((minGainRelative +1) / (spot_increase)) * self.capital_to_invest
        assert to_be_invested_in_spot < self.capital_to_invest, "gain_when_bet_looses is not possible"
        to_be_invested_in_bet = self.capital_to_invest - to_be_invested_in_spot

        return to_be_invested_in_bet, to_be_invested_in_spot

    # def get_anual_profit_for_payoff_curve(self, relativeProfit: np.ndarray) -> np.ndarray:
    #     """
    #     Converts the relative profit to annual profit.
    #     relativeProfit: np.ndarray of shape (n,) with relative profit values
    #     """
    #     closingDate = getClosingDateMarket(self.polymarket)
    #     if closingDate is None:
    #         return None
    #     currentDate = datetime.now()
    #     timeInTheMarket = closingDate - currentDate
    #     if relativeProfit is None:
    #         return None
    #     return (relativeProfit/timeInTheMarket.days) * 365

    # @staticmethod
    # def get_interest_rate_for_remaining_time(anual_interest_rate, timedelta):
    #     return (anual_interest_rate / 365) * timedelta.days

    def calculate_pay_off_curve_buy_now_and_hold(self, spot_prices:np.ndarray):
        """
        Calculates the pay-off curve for given final prices when the strategy is to buy and hold.

        raises Error if data might be corrupt
        returns None if the curve is not possible to be calculated

        returns array of same shape as spot_prices with relative profit values for every bitcoin value
        """
        currentSpotMarketPrice = self.cryptoSpotMarket.get_best_ask_price() # simple assumption market is liquid/our order is super small -> no price change in orderbook
        
        strike = self.polyMarketBetCryptoPrice.get_strike_price()
        if strike < currentSpotMarketPrice:
            raise ValueError(f"strike {strike} must be greater than currentSpotMarketPrice {currentSpotMarketPrice}")
        to_be_invested_in_bet, to_be_invested_in_spot = self._calculate_invest_size_for_spot_and_bet(currentSpotMarketPrice, strike)

        assert math.isclose(to_be_invested_in_bet + to_be_invested_in_spot, self.capital_to_invest, rel_tol=1e-5), "Invested capital is greater than available capital"

        print(f"Invested in bet: {to_be_invested_in_bet}, Invested in spot: {to_be_invested_in_spot}")
        avgPrice, shares = self.polyMarketBetCryptoPrice.get_price_and_shares_for_instant_buy(to_be_invested_in_bet)
        if shares is None:
            print("Too much capital needed for short hedge")
            return None
        bet_value_if_won = shares # shares resolve to 1$
        bet_value_if_lost = 0

        changeInPercent = spot_prices / currentSpotMarketPrice

        # 1.case spot increases and poly bet looses -> polyBetValue = 0, spotValue=increase in spot
        valueOfInvestments = changeInPercent[spot_prices >= strike] * to_be_invested_in_spot + bet_value_if_lost
        personal_profit_above_strike = valueOfInvestments -self.capital_to_invest

        #2. case spot stays under stirke bet wins
        valueOfInvestments = changeInPercent[spot_prices < strike] * to_be_invested_in_spot + bet_value_if_won
        personal_profit_below_strike = valueOfInvestments -self.capital_to_invest
        personalAbsoluteProfitDistribution = np.concatenate([personal_profit_below_strike, personal_profit_above_strike])

        # TODO: return infodict
        return personalAbsoluteProfitDistribution / self.capital_to_invest