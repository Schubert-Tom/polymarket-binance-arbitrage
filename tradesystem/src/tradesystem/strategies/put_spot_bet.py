import numpy as np
import math

# - own - # 
from tradesystem.domain.market import BetMarket, FutureMarket, SpotMarket

class PutSpotBet_ArbitrageStrategy:
    """
    This strategy goes long short:
    * Short on Polymarket,
    * Spot on binance,
    * Put option on binance

    IMPORTANT:
    This strategy assumes buy and hold and does not react on market movement.
    --> Can lead to losses as we see in calculate_pay_off_curve_buy_and_hold.
    This strategy can be used as a base for more advanced strategies.

    Inputs:
    - capital_to_invest: the amount of capital to invest in the strategy
    - bitcoin_market: the current state of the bitcoin market
    - polymarket: the current state of the polymarket
    - put future market: the current state of the put future market
    - minrelativeGainWhenBetIsLost: the minimum relative gain we want to have when the bet is lost (default 0.0 means we want to break even at least)

    Algorithm infos:
    * We go long on Binance and short on Polymarket with a binary option product (bet).
    * We only trade bitcoin on binance and keep the bet on polymarket until the market closes.
    * We keep the put future market as a hedge to cover for big losses (bigger than bet hedge)
    * The sum of investments at bet strike price shall be bigger than the investment by minrelativeGainWhenBetIsLost
    * We only return arbitrage opportunities
    * We consider liquidity of the markets of put and bet market and assume spot market to be very liquid

    !! Risks !!:
    Even for markets which show arbitrage opportunities the strategy can lead to losses because of the following reasons:
        * no fees are considered
        * Binance put option market and polymarket closing dates are not the same. (To be 100% sure polymarket must close before put option expires, which is not enforced in the code)
        * Binance and polymarket are legally not allowed to be used in some countries (e.g. polymarket -> USA)
        * Binance put option markets assumes min_quantity of 0.01 contracts. This strategy does not consider that --> scaling to 0.01 steps might change fee structure

    """
    def __init__(self, capital_to_invest:float, cryptoSpotMarket:SpotMarket, cryptoPutMarket:FutureMarket, polyMarketBet:BetMarket, minrelativeGainWhenBetIsLost = 0.0):
        self.capital_to_invest = capital_to_invest
        self.minrelativeGainWhenBetIsLost = minrelativeGainWhenBetIsLost

        assert isinstance(cryptoSpotMarket, SpotMarket), "cryptoSpotMarket must be a SpotMarket"
        assert isinstance(polyMarketBet, BetMarket), "polyMarketBet must be a BetMarket"
        assert isinstance(cryptoPutMarket, FutureMarket), "cryptoPutMarket must be a FutureMarket"

        # TODO: normally this must be true but if bet payout factor is >= 2 one could sell all at put strike and expect that in the time delta btc does not go up to poly strike
        # print(polyMarketBet.expirationDate, cryptoPutMarket.get_expiration_date())
        # assert polyMarketBet.expirationDate < cryptoPutMarket.get_expiration_date(), "Polymarket bet must expire before put market"
        assert cryptoSpotMarket.get_underlying_currency() == cryptoPutMarket.get_underlying_currency(), f"Both markets must have the same underlying currency, got {cryptoSpotMarket.get_underlying_currency()} and {cryptoPutMarket.get_underlying_currency()}"

        # TODO polymarket shares are in USD
        # polyMarketBet.get_underlying_currency()

        self.cryptoSpotMarket = cryptoSpotMarket
        self.polyMarketBet = polyMarketBet
        self.cryptoPutMarket = cryptoPutMarket

    def _allocate_consider_liquidity_no_fees(self, spotPrice, bet_strike, put_strike):
        """
        Here we want to find out what share of our capital we want to invest in each market.
        This is just some math to find an allocation and does not need to be understood by a user of the class.
        Relevant is only if the resulting p&l curve shows arbitrage or not.
        Also this is not the optimal allocation but a good guess for this strategy.
        It does not find the global optimum + does not consider fees.
        
        Important:
        We need to consider the liquidity of the markets.
        Therefore we consider the spot market to be very liquid to make calculations easier.
        We set the anchor point to the strike price where the bet is lost.
        At this anchor point we want the following equation to be true:

        spot * r - bet - put = c, where r=spot/strike -1

        For that we draw from the orderbook of the bet market and check what kind of put we can cover with that

        We draw from the orderbook to determine the optimal allocation
        The optimization boundaries are as follows:
            1. The put hedge should always cover the spot losses, even in extreme cases (BTC down to 0$)
            2. The put hedge shares must cover the corresponding btc spot shares
            3. The resulting p&l curve in case of btc going down must cross break even below the put strike price to ensure put covers spot/bet losses
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
            bet_price_avg, bet_shares = self.polyMarketBet.get_price_and_shares_for_instant_buy(to_be_invested_in_bet)
            put_price_avg, put_shares = self.cryptoPutMarket.get_price_and_shares_for_instant_buy(to_be_invested_in_put)

            if put_shares is None:
                put_price_avg = 0.0
                put_shares = 0.0

            # check the intersection of profit curve with 0 for the current allocation
            # if this is bigger than the strike and c can cover the cost of the put we found arbitrage
            m = (to_be_invested_in_spot * (bet_strike/spotPrice-1)) / (bet_strike - spotPrice)
            b = ((bet_shares - bet_shares*bet_price_avg) - put_price_avg * put_shares) - m * spotPrice
            intersection = -b/m

            if (put_strike > intersection) and put_shares >= to_be_invested_in_spot/spotPrice:
                # We want to find the closest c to put_strike sweeping from the right side
                # The c which we want to find should allow slim protection but keep as much potential to the upperlimit
                arbCandidates.append((to_be_invested_in_bet, to_be_invested_in_spot, to_be_invested_in_put))

        return arbCandidates[0] if len(arbCandidates) > 0 else (0,0,0)

    def calculate_profit_loss_curve(self, spot_prices:np.ndarray):
        """
        Calculates the profit and loss curve for given final prices when the strategy is to buy and hold.

        raises Error if data might be corrupt
        returns None if the curve is not possible to be calculated

        returns array of same shape as spot_prices with relative profit values for every bitcoin value
        """
        currentSpotMarketPrice = self.cryptoSpotMarket.get_best_ask_price() # assume market is liquid and we do not move the market with our buy
        strike_poly = self.polyMarketBet.get_strike_price()
        strike_put = self.cryptoPutMarket.get_strike_price()

        to_be_invested_in_bet, to_be_invested_in_spot, to_be_invested_in_put = self._allocate_consider_liquidity_no_fees(currentSpotMarketPrice, strike_poly, strike_put)

        avgBetPrice, shares = self.polyMarketBet.get_price_and_shares_for_instant_buy(to_be_invested_in_bet)
        avgPutPrice, put_shares = self.cryptoPutMarket.get_price_and_shares_for_instant_buy(to_be_invested_in_put)

        bet_value_if_won = shares if shares else 0 # shares resolve to 1$
        bet_value_if_lost = 0


        if to_be_invested_in_bet + to_be_invested_in_spot + to_be_invested_in_put != self.capital_to_invest:
            return {}


        changeInPercent = spot_prices / currentSpotMarketPrice
        # 1.case spot increases and poly bet looses -> 
        #       * polyBetValue = 0, 
        #       * spotValue=increase
        #       * putValue=0
        valueOfInvestments = (changeInPercent[spot_prices >= strike_poly] * to_be_invested_in_spot) + bet_value_if_lost
        personal_profit_above_strike = valueOfInvestments - self.capital_to_invest

        #2. case spot stays under poly_strike -> bet is won
        #       * polyBetValue = bet_value_if_won, 
        #       * spotValue=increase or decrease
        #       * putValue=0
        valueOfInvestments = (changeInPercent[(spot_prices < strike_poly) & (spot_prices >= strike_put)] * to_be_invested_in_spot) + bet_value_if_won
        personal_profit_below_strike_poly = valueOfInvestments - self.capital_to_invest

        #3. case below strike_put
        #       * polyBetValue = bet_value_if_won, 
        #       * spotValue=decrease
        #       * putValue= in the money
        put_value_in_the_money = (strike_put - spot_prices[spot_prices < strike_put])  * put_shares
        valueOfInvestments = (changeInPercent[spot_prices < strike_put] * to_be_invested_in_spot) + bet_value_if_won + put_value_in_the_money
        personal_profit_below_strike_put = valueOfInvestments - self.capital_to_invest

        personalAbsoluteProfitDistribution = np.concatenate([personal_profit_below_strike_put, personal_profit_below_strike_poly, personal_profit_above_strike])


        # fill info dict
        calulation_results = {}
        calulation_results["to_be_invested_in_bet"] = to_be_invested_in_bet
        calulation_results["to_be_invested_in_spot"] = to_be_invested_in_spot
        calulation_results["to_be_invested_in_put"] = to_be_invested_in_put
        calulation_results["cryptoPutMarket"] = self.cryptoPutMarket
        calulation_results["polyMarketBet"] = self.polyMarketBet
        calulation_results["cryptoSpotMarket"] = self.cryptoSpotMarket
        calulation_results["capital_invested"] = self.capital_to_invest
        calulation_results["bet_value_if_won"] = bet_value_if_won
        calulation_results["bet_value_if_lost"] = bet_value_if_lost
        calulation_results["put_shares"] = put_shares
        calulation_results["personalAbsoluteProfitDistribution"] = personalAbsoluteProfitDistribution
        calulation_results["personalRelativeProfitDistribution"] = personalAbsoluteProfitDistribution / self.capital_to_invest
        calulation_results["avgBetPrice"] = avgBetPrice
        calulation_results["avgPutPrice"] = avgPutPrice
        calulation_results["minRelativeGainWhenBetIsLost"] = self.minrelativeGainWhenBetIsLost
        calulation_results["arbitrage"] = True if np.min(calulation_results["personalRelativeProfitDistribution"]) > 0 else False
        calulation_results["currentSpotMarketPrice"] = currentSpotMarketPrice

        return calulation_results