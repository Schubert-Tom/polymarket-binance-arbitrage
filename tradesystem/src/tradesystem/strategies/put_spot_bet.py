import numpy as np
import math

# - own - # 
from tradesystem.domain.market import BetMarket, FutureMarket, SpotMarket

class PutSpotBetStrategy:
    """
    This strategy goes long short:
    * Short on Polymarket,
    * Spot on binance,
    * Put option on binance

    This strategy assumes buy and hold and does not react on market movement.
    --> Can lead to losses as we see in calculate_pay_off_curve_buy_and_hold.
    This strategy can be used as a base for more advanced strategies.

    Inputs:
    - capital_to_invest: the amount of capital to invest in the strategy (relevant since polymarket is not as liquid)
    - bitcoin_market: the current state of the bitcoin market
    - polymarket: the current state of the polymarket
    - put future market: the current state of the put future market

    Algorithm:
    We go long on Binance and short on Polymarket.
    We only trade bitcoin on binance and keep the bet on polymarket until the market closes.
    We keep the put future market as a hedge to cover for big losses (bigger than bet hedge)
    First we check we have no losses on long side, then we try to get a suitable hedge to cover
    """
    def __init__(self, capital_to_invest:float, cryptoSpotMarket:SpotMarket, cryptoPutMarket:FutureMarket, polyMarketBetCryptoPrice:BetMarket, minrelativeGainWhenBetIsLost = 0.0):
        self.capital_to_invest = capital_to_invest
        self.minrelativeGainWhenBetIsLost = minrelativeGainWhenBetIsLost

        assert isinstance(cryptoSpotMarket, SpotMarket), "cryptoSpotMarket must be a SpotMarket"
        assert isinstance(polyMarketBetCryptoPrice, BetMarket), "polyMarketBetCryptoPrice must be a BetMarket"
        assert isinstance(cryptoPutMarket, FutureMarket), "cryptoPutMarket must be a FutureMarket"

        # TODO: normally this must be true but if bet payout factor is >= 2 one could sell all at put strike and expect that in the time delta btc does not go up to poly strike
        # print(polyMarketBetCryptoPrice.expirationDate, cryptoPutMarket.get_expiration_date())
        # assert polyMarketBetCryptoPrice.expirationDate < cryptoPutMarket.get_expiration_date(), "Polymarket bet must expire before put market"
        assert cryptoSpotMarket.get_underlying_currency() == cryptoPutMarket.get_underlying_currency(), f"Both markets must have the same underlying currency, got {cryptoSpotMarket.get_underlying_currency()} and {cryptoPutMarket.get_underlying_currency()}"

        # TODO polymarket shares are in USD
        # polyMarketBetCryptoPrice.get_underlying_currency()

        self.cryptoSpotMarket = cryptoSpotMarket
        self.polyMarketBetCryptoPrice = polyMarketBetCryptoPrice
        self.cryptoPutMarket = cryptoPutMarket

    def _allocate_consider_liquidity(self, spotPrice, bet_strike, put_strike):
        """
        Here we want to find out what share of our capital we want to invest in each market.
        
        Important:
        We need to consider the liquidity of the markets.
        Therefore we consider the spot market to be very liquid to make calculations easier.
        We set the anchor point to the strike price where the bet is lost.
        At this anchor point we want the following equation to be true:

        spot * r - bet - put = c, where r=spot/strike -1

        For that we draw from the orderbook of the bet market and check what kind of put we can cover with that

        We draw from the orderbook to determine the optimal allocation
        The optimization boundaries are as follows:
        1. The put hedge should always cover the spot losses

        """
        assert isinstance(bet_strike, float), "upwardslimit must be a float"

        def _bet_and_spot(spotPrice, bet_strike , c_relative):
            """
            Calculates the capital allocation in spot and bet market by setting the anchor point to the price where the bet is lost.
            At this anchor point we want at least c_relative to be covered, which is a percentage of the invested capital
            """
            assert isinstance(bet_strike, float), "upwardslimit must be a float"
            spot_increase = bet_strike / spotPrice

            spot_relative = (1 + self.minrelativeGainWhenBetIsLost) / spot_increase
            bet_relative = 1 - spot_relative - c_relative

            if spot_relative <0 or bet_relative < 0:
                return None, None, None


            to_be_invested_in_bet = bet_relative * self.capital_to_invest
            to_be_invested_in_spot = spot_relative * self.capital_to_invest
            to_be_invested_in_put = c_relative * self.capital_to_invest

            return to_be_invested_in_bet, to_be_invested_in_spot, to_be_invested_in_put

        # sweep over different put prices and see which one covers the loss
        arbCandidates = []
        for c in np.arange(0, 0.75, 0.001):
            to_be_invested_in_bet, to_be_invested_in_spot, to_be_invested_in_put = _bet_and_spot(spotPrice, bet_strike, c)
            if to_be_invested_in_bet is None or to_be_invested_in_spot is None:
                continue
            if to_be_invested_in_bet <= 0 or to_be_invested_in_spot <= 0:
                continue
            bet_price_avg, bet_shares = self.polyMarketBetCryptoPrice.get_price_and_shares_for_instant_buy(to_be_invested_in_bet)
            put_price_avg, put_shares = self.cryptoPutMarket.get_price_and_shares_for_instant_buy(to_be_invested_in_put)

            if put_shares is None:
                put_price_avg = 0.0
                put_shares = 0.0


            # check the intersection of profit curve with 0 for the current allocation
            # if this is bigger than the strike and c can cover the cost of the put we found arbitrage
            m = (to_be_invested_in_spot * (bet_strike/spotPrice-1)) / (bet_strike - spotPrice)
            b = ((bet_shares - bet_shares*bet_price_avg) - put_price_avg * put_shares) - m * spotPrice
            
            # putInvest = put_price_avg * put_shares

            # dd = m*spotPrice + b
            
            intersection = -b/m
            if (put_strike > intersection) and put_shares >= to_be_invested_in_spot/spotPrice:
                # We want to find the closest c to put_strike coming from the right side
                # The c which we want to find should allow slim protection but keep as much potential to the upperlimit
                arbCandidates.append((to_be_invested_in_bet, to_be_invested_in_spot, to_be_invested_in_put))

        return arbCandidates[0] if len(arbCandidates) > 0 else (0,0,0)

    def calculate_pay_off_curve_buy_now_and_hold(self, spot_prices:np.ndarray):
        """
        Calculates the pay-off curve for given final prices when the strategy is to buy and hold.

        raises Error if data might be corrupt
        returns None if the curve is not possible to be calculated

        returns array of same shape as spot_prices with relative profit values for every bitcoin value
        """
        currentSpotMarketPrice = self.cryptoSpotMarket.get_best_ask_price() # assume market is liquid and we do not move the market with our buy
        strike_poly = self.polyMarketBetCryptoPrice.get_strike_price()
        strike_put = self.cryptoPutMarket.get_strike_price()

        # spot_put_ratio = currentSpotMarketPrice / currentPutMarketPrice
        # betPayoutFactor = 1 / avgPrice
        # spotPayoutFactor = (strike_put-currentSpotMarketPrice)/currentSpotMarketPrice
        to_be_invested_in_bet, to_be_invested_in_spot, to_be_invested_in_put = self._allocate_consider_liquidity(currentSpotMarketPrice, strike_poly, strike_put)

        avgBetPrice, shares = self.polyMarketBetCryptoPrice.get_price_and_shares_for_instant_buy(to_be_invested_in_bet)
        avgPutPrice, put_shares = self.cryptoPutMarket.get_price_and_shares_for_instant_buy(to_be_invested_in_put)

        bet_value_if_won = shares if shares else 0 # shares resolve to 1$
        bet_value_if_lost = 0

        changeInPercent = spot_prices / currentSpotMarketPrice

        if to_be_invested_in_bet + to_be_invested_in_spot + to_be_invested_in_put != self.capital_to_invest:
            # print(f"No arbitrage possible with current markets, invested {to_be_invested_in_bet + to_be_invested_in_spot + to_be_invested_in_put} of {self.capital_to_invest}")
            return {}

        # 1.case spot increases and poly bet looses -> polyBetValue = 0, spotValue=increase in spot
        valueOfInvestments = changeInPercent[spot_prices >= strike_poly] * to_be_invested_in_spot + bet_value_if_lost
        personal_profit_above_strike = valueOfInvestments -self.capital_to_invest

        #2. case spot stays under poly_strike
        # valueOfInvestments = changeInPercent[(spot_prices < strike_poly) & (spot_prices > strike_put)] * to_be_invested_in_spot + bet_value_if_won
        valueOfInvestments = changeInPercent[(spot_prices < strike_poly) & (spot_prices >= strike_put)] * to_be_invested_in_spot + bet_value_if_won
        personal_profit_below_strike_poly = valueOfInvestments -self.capital_to_invest

        #3. case below strike_put
        put_value_in_the_money = (strike_put - spot_prices[spot_prices < strike_put])  * put_shares
        valueOfInvestments = changeInPercent[spot_prices < strike_put] * to_be_invested_in_spot + bet_value_if_won + put_value_in_the_money
        personal_profit_below_strike_put = valueOfInvestments -self.capital_to_invest

        
        personalAbsoluteProfitDistribution = np.concatenate([personal_profit_below_strike_put, personal_profit_below_strike_poly, personal_profit_above_strike])
        # fill info dict
        calulation_infos = {}
        calulation_infos["to_be_invested_in_bet"] = to_be_invested_in_bet
        calulation_infos["to_be_invested_in_spot"] = to_be_invested_in_spot
        calulation_infos["to_be_invested_in_put"] = to_be_invested_in_put
        calulation_infos["cryptoPutMarket"] = self.cryptoPutMarket
        calulation_infos["polyMarketBetCryptoPrice"] = self.polyMarketBetCryptoPrice
        calulation_infos["cryptoSpotMarket"] = self.cryptoSpotMarket
        calulation_infos["capital_invested"] = self.capital_to_invest
        calulation_infos["bet_value_if_won"] = bet_value_if_won
        calulation_infos["bet_value_if_lost"] = bet_value_if_lost
        calulation_infos["put_shares"] = put_shares
        calulation_infos["personalAbsoluteProfitDistribution"] = personalAbsoluteProfitDistribution
        calulation_infos["personalRelativeProfitDistribution"] = personalAbsoluteProfitDistribution / self.capital_to_invest
        calulation_infos["avgBetPrice"] = avgBetPrice
        calulation_infos["avgPutPrice"] = avgPutPrice
        calulation_infos["minRelativeGainWhenBetIsLost"] = self.minrelativeGainWhenBetIsLost
        calulation_infos["arbitrage"] = True if to_be_invested_in_bet + to_be_invested_in_spot + to_be_invested_in_put == self.capital_to_invest else False
        calulation_infos["currentSpotMarketPrice"] = currentSpotMarketPrice

        return calulation_infos