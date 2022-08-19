import csv
import math
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Union
import ib_insync as ibi


@dataclass
class Investment:
    stock: ibi.Stock
    allocation: float
    num_shares: float = None
    market_price: float = None
    shares_to_purchase: float = None


class MarketDataGetter:
    def __init__(self, connector: ibi.IB):
        self.connector = connector
        if self.connector.isConnected() is False:
            raise ValueError("Must be connected")

    def get_market_value(self, symbol: str, timeout: float = 10):
        stock = ibi.Stock(symbol, exchange="SMART", currency="USD")
        ticker = self.connector.reqMktData(stock, "", False, False)
        s = time.time()
        while math.isnan(ticker.marketPrice()) and math.isnan(ticker.last):
            if 0 < timeout <= time.time() - s:
                raise ValueError(f"Took to long to get data for symbol {symbol}")
            self.connector.sleep(0.5)
            ticker = self.connector.ticker(stock)
        return ticker.marketPrice()


class CurrentPortfolio:
    def __init__(self, connector: ibi.IB):
        self.connector = connector
        if self.connector.isConnected() is False:
            raise ValueError("Must be connected")
        self.portfolio = self.get_portfolio()

    def get_portfolio(self) -> List[ibi.PortfolioItem]:
        return self.connector.portfolio()

    def contains(self, symbol):
        for item in self.portfolio:
            if item.contract.symbol == symbol:
                return True
        return False

    def get(self, symbol: str) -> ibi.PortfolioItem:
        for item in self.portfolio:
            if item.contract.symbol == symbol:
                return item
        raise KeyError(f"{symbol} not currently in portfolio")


class AccountInfo:
    def __init__(self, connector: ibi.IB):
        self.connector = connector

    def available_cash(self):
        funds = [
            float(v.value)
            for v in self.connector.accountValues()
            if v.tag == "AvailableFunds"
        ][0]
        return funds


class Plan:
    def __init__(self, investments: List[Investment]):
        self.investments = investments
        self.validate_allocations()

    def validate_allocations(self):
        total_allocation = sum(
            [investment.allocation for investment in self.investments]
        )
        if total_allocation != 1.0:
            raise ValueError(f"Total allocation sum to 1: {total_allocation:0.4f}")

    def calculate_total_stock_value(self):
        total = sum([i.market_price * i.num_shares for i in self.investments])
        return total

    def calculate_total_value(self, available_cash: float):
        stock_value = self.calculate_total_stock_value()
        total = stock_value + available_cash
        return total

    def calculate_shares_to_purchase(self, available_cash: float):
        total_value = self.calculate_total_value(available_cash)
        for investment in self.investments:
            desired_value = investment.allocation * total_value
            desired_num_shares = desired_value / investment.market_price
            current_num_shares = investment.num_shares
            shares_to_purchase = desired_num_shares - current_num_shares
            investment.shares_to_purchase = shares_to_purchase
        return self.investments


class PlanReader:
    @classmethod
    def read_plan(cls, path: str) -> Plan:
        rows = cls._load_file(path)
        investments = []
        for row in rows:
            stock = ibi.Stock(symbol=row["stock"], exchange="SMART", currency="USD")
            allocation = float(row["allocation"])
            investments.append(Investment(stock, allocation))
        return Plan(investments)

    @classmethod
    def _load_file(cls, path: str) -> List[Dict[Any, Any]]:
        with open(path) as f:
            dr = csv.DictReader(f)
            return [row for row in dr]


class PlanCompleter:
    def __init__(self, connector: ibi.IB):
        self.connector = connector

    def complete_plan(self, plan: Plan, portfolio: CurrentPortfolio) -> Plan:
        for investment in plan.investments:
            if portfolio.contains(investment.stock.symbol):
                portfolio_item = portfolio.get(investment.stock.symbol)
                market_price = portfolio_item.marketPrice
                num_shares = portfolio_item.position
            else:
                data_getter = MarketDataGetter(connector=self.connector)
                market_price = data_getter.get_market_value(investment.stock.symbol)
                num_shares = 0
            investment.market_price = market_price
            investment.num_shares = num_shares
        return plan


class OrderMaker:
    def __init__(self, connector: ibi.IB):
        self.connector = connector

    def order(
        self, investment: Investment, test: bool = True, num_shares: float = None
    ) -> Union[ibi.Trade, ibi.OrderState]:
        contract = investment.stock
        self.connector.qualifyContracts(contract)
        if num_shares is None:
            num_shares = math.floor(investment.shares_to_purchase)
        order = ibi.MarketOrder(action="BUY", totalQuantity=num_shares)
        if test is True:
            return self.connector.whatIfOrder(contract=contract, order=order)
        else:
            return self.connector.placeOrder(contract=contract, order=order)


if __name__ == "__main__":
    ib = ibi.IB()
    ib.connect("127.0.0.1", port=7496, clientId=123)
    portfolio = CurrentPortfolio(connector=ib)
    plan = PlanReader.read_plan("config/plan.csv")
    plan = PlanCompleter(ib).complete_plan(plan=plan, portfolio=portfolio)
    available_cash = AccountInfo(connector=ib).available_cash()
    investments = plan.calculate_shares_to_purchase(available_cash)
