# coding: utf-8

import argparse
from collections import namedtuple
import csv
from dataclasses import dataclass
import math
import random
import time
import json
import requests
import logging
import urllib3

from urllib3.exceptions import InsecureRequestWarning
from initial_login import login_to_ibkr
from ibkr_session import IBKRSession, RequestException

urllib3.disable_warnings(category=InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Field:
    LAST_PRICE = "31"
    MARKET_VALUE = "73"
    DATA_INFO = "6509"
    HAS_TRADING_PERMISSION = "7768"

    @classmethod
    def join(cls, **fields):
        return ",".join(fields)


class Stock:
    session = IBKRSession()

    def __init__(
        self,
        symbol: str,
        conid: int = None,
        exchange: str = None,
        currency: str = None,
        session: IBKRSession = None,
    ):
        self.symbol = symbol
        self.conid = conid
        self.exchange = exchange
        self.currency = currency
        if session is not None:
            self.session = session
        if self.conid is None or self.exchange is None:
            self.complete_information()
        self.price = None
        self.price_updated = None

    @classmethod
    def by_conid(cls, conid: str, session: IBKRSession = None):
        session = cls.session if session is None else session
        result = session.get("trsrv/secdef", params={"conids": str(conid)})
        contract = result["secdef"][0]
        return cls(
            symbol=contract["ticker"],
            conid=contract["conid"],
            exchange=contract["listingExchange"],
            currency=contract["currency"],
        )

    @classmethod
    def by_symbol(cls, symbol: str, session: IBKRSession = None):
        session = cls.session if session is None else session
        params = {"symbols": symbol}
        response = session.get("trsrv/stocks", params=params)
        if "error_code" in response:
            raise Exception(response)
        results = response[symbol]
        for result in results:
            for contract in result["contracts"]:
                if contract["isUS"] is True:
                    conid = contract["conid"]
                    return cls.by_conid(conid, session=session)
        raise Exception(f"Could not find stock with {symbol=} on a US exchange: {results}")

    def complete_information(self):
        if self.conid is not None:
            stock = self.by_conid(self.conid)
        else:
            stock = self.by_symbol(symbol=self.symbol)
        self.conid = stock.conid
        self.exchange = stock.exchange

    @classmethod
    def update_prices(cls, stocks: list["Stock"], max_tries: int = 10, sleep_interval: float = 0.5):
        # TODO fix
        conid2stock = {stock.conid: stock for stock in stocks}
        conid_str = ",".join([str(stock.conid) for stock in stocks])
        for i in range(max_tries):
            responses = cls.session.get(
                "/iserver/marketdata/snapshot", params={"conids": conid_str, "fields": Field.LAST_PRICE}
            )
            updated = False
            for response in responses:
                if Field.LAST_PRICE in response:
                    updated = True
                    try:
                        price = response[Field.LAST_PRICE]
                        price_without_close_prefix = price.replace("C", "")
                        conid2stock[response["conid"]].price = float(price_without_close_prefix)
                        conid2stock[response["conid"]].price_updated = time.time()
                    except ValueError:
                        print(f"Problem getting price: {response=}")
                        raise
            if updated:
                return stocks
            time.sleep(sleep_interval)
        raise TimeoutError(f"Could not get latest price for {self}. Last response: {response}")

    def update_latest_price(self, max_tries: int = 10, sleep_interval: float = 0.5):
        self.session.get(
            "/iserver/marketdata/snapshot",
            params={"conids": self.conid, "fields": Field.LAST_PRICE},
        )
        for i in range(10):
            response = self.session.get("/iserver/marketdata/snapshot", params={"conids": self.conid})
            response = response[0]
            if Field.LAST_PRICE in response:
                try:
                    price = response[Field.LAST_PRICE]
                    price_without_close_prefix = price.replace("C", "")
                    self.price = float(price_without_close_prefix)
                except ValueError:
                    print(f"Problem getting price for {self.symbol=}: {response=}")
                    raise
                self.price_updated = time.time()
                return self.price
            time.sleep(sleep_interval)
        raise TimeoutError(f"Could not get latest price for {self}. Last response: {response}")

    def __repr__(self):
        symbol = self.symbol
        conid = self.conid
        exchange = self.exchange
        price = self.price
        return f"Stock({symbol=}, {conid=}, {exchange=}, {price=})"


@dataclass
class Position:
    stock: Stock
    num_shares: float
    market_value: float


class Portfolio:

    def __init__(self, account_id: int, session: IBKRSession = IBKRSession()):
        self.session = session
        self.account_id = account_id
        self.positions = []
        self.update_positions()

    def update_positions(self) -> list[Position]:
        self.positions = self.update_positions_for_account(self.account_id)
        return self.positions

    def update_positions_for_account(self, account_id: int) -> list[Position]:
        finished = False
        page = 0
        positions = []
        while not finished:
            result = self.session.get(f"/portfolio/{account_id}/positions/{page}")
            page += 1
            finished = len(result) == 0
            for row in result:
                if row["assetClass"] != "STK":
                    continue
                symbol = row.get("ticker", row["contractDesc"])
                stock = Stock(symbol=symbol, conid=row["conid"], currency=row["currency"])
                position = self.get_position(stock=stock, create_if_needed=True)
                position.num_shares = row["position"]
                position.market_value = row["mktValue"]
                positions.append(position)
        return positions

    def get_position(self, stock: Stock | str, create_if_needed: bool = False) -> Position:
        symbol = stock.symbol if isinstance(stock, Stock) else str(stock)
        position = [p for p in self.positions if p.stock.symbol == symbol]
        if len(position) == 0:
            if create_if_needed is True:
                stock = stock if isinstance(stock, Stock) else Stock.by_symbol(symbol)
                return Position(stock, num_shares=0.0, market_value=0.0)
            raise Exception(f"You currently don't own any {symbol=}")
        position = position[0]
        return position

    def total_value(self):
        return sum([position.market_value for position in self.positions])


class Order:
    session = IBKRSession()

    def __init__(self, account_id: int):
        self.account_id = account_id
        self.order_id = None
        self.order_status = None

    def order(self, side: str, stock: Stock, num_shares: int, type: str = "MKT", price: float = None):
        assert type.upper() in ["MKT", "LMT"], f"type must be 'MKT' or 'LMT' not {type}"
        assert side.upper() in ["BUY", "SELL"], f"type must be 'BUY' or 'SELL' not {side}"
        order = {"conid": stock.conid, "side": side, "orderType": type, "quantity": num_shares, "tif": "DAY"}
        if type == "LMT":
            if price is None:
                price = stock.price
            order["price"] = price
        result = self.session.post(f"/iserver/account/{self.account_id}/orders", json_payload={"orders": [order]})
        if isinstance(result, list):
            result = result[0]
        if "id" in result:
            logger.error(f"Need to confirm first: {result['message']=}")
            confirmation_id = result["id"]
            result = self.session.post(f"/iserver/reply/{confirmation_id}", json_payload={"confirmed": True})
        if isinstance(result, list):
            result = result[0]
        if "error" in result:
            raise Exception(f"Order did not go through: {result['error']=}")
        self.order_id = result.get("order_id")
        self.order_status = result.get("status")
        return result

    def buy(self, stock: Stock, num_shares: int, type: str = "MKT", price: float = None):
        return self.order(side="BUY", stock=stock, num_shares=num_shares, type=type, price=price)

    def sell(self, stock: Stock, num_shares: int, type: str = "MKT", price: float = None):
        return self.order(side="SELL", stock=stock, num_shares=num_shares, type=type, price=price)

    def update_status(self):
        results = self.session.get(f"/iserver/account/orders", params={"force": "true", "accountId": self.account_id})
        logger.info(f"Order status: {json.dumps(results, indent=2)}")
        self.order_status = results["orders"]
        return results


class Account:
    TICKER = "USD.ILS"
    USD_ILS_CONID = 44495102

    def __init__(self, account_id: int, session: IBKRSession = IBKRSession()):
        self.session = session
        self.account_id = account_id
        self.ils_cash = 0
        self.usd_cash = 0
        self.order_id = None
        self.order_status = None

    def initialize(self):
        try:
            self.initialize_ibkr_session()
        except RequestException as exc:
            error_info = exc.args[0]
            if error_info["error_code"] == 401:
                login_to_ibkr()
                self.initialize_ibkr_session()
            else:
                raise
        self.set_account()

    def initialize_ibkr_session(self):
        res = self.session.post("/iserver/auth/ssodh/init", json_payload={"publish": True, "compete": True})

    def set_account(self):
        result = self.session.post(
            "/iserver/account",
            json_payload={"acctId": self.account_id},
            raise_on_error=False,
        )

    def update_cash_balances(self):
        ledger = self.session.get(f"/portfolio/{self.account_id}/ledger")
        for currency, data in ledger.items():
            if currency == "ILS":
                self.ils_cash = data["cashbalance"]
            elif currency == "USD":
                self.usd_cash = data["cashbalance"]

    def convert_all_ils_to_usd(self):
        TWO_DOLLAR_AMOUNT = 4
        amount_to_convert = self.ils_cash - TWO_DOLLAR_AMOUNT
        if amount_to_convert < 0:
            logger.error(f"Amount to convert would make balance negative: {self.ils_cash=} {amount_to_convert=}")
            return
        return self.convert_to_usd()

    def convert_to_usd(self, amount_in_ils: float):
        data = {
            "orders": [
                {
                    "conid": self.USD_ILS_CONID,
                    "ticker": self.TICKER,
                    "fxQty": amount_in_ils,
                    "isCcyConv": True,
                    "orderType": "MKT",
                    "side": "BUY",
                    "tif": "DAY",
                    "cOID": f"'{amount_in_ils} ILS -> USD'",
                }
            ]
        }
        logger.info("Currency Conversion")
        result = self.session.post(f"/iserver/account/{self.account_id}/orders", json_payload=data)
        logger.info(f"Received result: {result}")
        if isinstance(result, list):
            result = result[0]
        if "id" in result:
            logger.error(f"Need to confirm first: {result['message']=}")
            confirmation_id = result["id"]
            result = self.session.post(f"/iserver/reply/{confirmation_id}", json_payload={"confirmed": True})
        if "error" in result:
            raise Exception(f"Currency conversion order did not go through: {result['error']=}")
        logger.info(f"Received result: {result}")
        self.order_id = result["order_id"]
        self.order_status = result["order_status"]

    def get_order_status(self):
        result = self.session.get(f"/iserver/account/orders", params={"force": "true"})
        logger.info(f"Order status: {json.dumps(result, indent=2)}")
        return result


@dataclass
class InvestmentPlan:
    stock: Stock
    allocation: float
    shares_to_purchase: int = 0
    shares_desired: float = 0
    offset_from_desired: float = 0

    def update(self):
        self.stock.update_latest_price()


class PlanReader:
    @classmethod
    def read_plan(cls, path: str) -> list[InvestmentPlan]:
        rows = cls._load_file(path)
        investments = []
        for row in rows:
            stock = Stock.by_symbol(row["stock"])
            allocation = float(row["allocation"])
            investments.append(InvestmentPlan(stock, allocation))
        return investments

    @classmethod
    def _load_file(cls, path: str) -> list[dict]:
        with open(path) as f:
            dr = csv.DictReader(f)
            return [row for row in dr]


class InvestmentPlanStrategy:
    def __init__(self, investments: list[InvestmentPlan]):
        self.investments = investments

    @property
    def total_allocated(self):
        return sum([investment.allocation for investment in self.investments])

    def run(self, portfolio: Portfolio, cash_available: float):
        total_value = portfolio.total_value() + cash_available
        for investment in self.investments:
            position = portfolio.get_position(stock=investment.stock, create_if_needed=True)
            investment.stock.price = position.stock.update_latest_price()
            desired_value = investment.allocation * total_value
            value_to_purchase = desired_value - position.market_value
            investment.offset_from_desired = value_to_purchase
            investment.shares_desired = value_to_purchase / investment.stock.price
        total_offset = sum([i.offset_from_desired for i in self.investments if i.offset_from_desired > 0])
        money_left = 0.0
        for investment in self.investments:
            fraction_of_allocation = investment.offset_from_desired / total_offset
            value_to_purchase = cash_available * fraction_of_allocation
            shares_to_purchase = value_to_purchase / investment.stock.price
            func = math.floor if shares_to_purchase > 0 else math.ceil
            nonfractional_num_shares = int(func(shares_to_purchase))
            investment.shares_to_purchase = nonfractional_num_shares
            leftover_money = (shares_to_purchase - nonfractional_num_shares) * position.stock.price
            leftover_money = max(leftover_money, 0)
            money_left += leftover_money
        return self.calculate_leftover_shares_to_purchase(money_left=money_left)

    def calculate_leftover_shares_to_purchase(self, money_left: float, by_offset: bool = True):
        idxs = list(range(len(self.investments)))
        if by_offset is True:
            idxs = sorted(idxs, key=lambda idx: self.investments[idx].shares_desired, reverse=True)
        else:
            random.shuffle(idxs)
        for idx in idxs:
            investment = self.investments[idx]
            if investment.stock.price <= money_left:
                investment.shares_to_purchase += 1
                money_left -= investment.stock.price
        return self.investments


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    return parser.parse_args()


def login(account_id) -> Account:
    account = Account(account_id=account_id)
    account.initialize()
    account.update_cash_balances()
    return account


def main(live: bool = False):
    account_id = "U3492785"
    account = login(accound_id=account_id)

    logger.info(f"Account contains {account.ils_cash} ILS and {account.usd_cash} USD")
    logger.info(f"Converting {account.ils_cash} ILS to USD")
    if live is True:
        account.convert_all_ils_to_usd()
    account.get_order_status()
    account.update_cash_balances()
    logger.info(f"Account now contains {account.ils_cash} ILS and {account.usd_cash} USD")

    portfolio = Portfolio(account_id=account_id)
    portfolio_value = portfolio.total_value()
    total_value = portfolio_value + account.usd_cash
    logger.info(f"{portfolio_value=}, USD cash={account.usd_cash}, {total_value=}")

    investments = PlanReader.read_plan("config/allocation.csv")
    total_fraction = sum([investment.allocation for investment in investments])
    if total_fraction != 1.0:
        raise Exception(f"Allocation values don't sum to 1: {total_fraction=}")

    investments = InvestmentPlanStrategy(investments=investments).run(
        portfolio=portfolio, cash_available=account.usd_cash
    )
    logger.info("Total share value: {total_shares:0.02f}")
    for investment in investments:
        logger.info(portfolio.get_position(investment.stock.symbol))
        logger.info(investment)
        if investment.shares_to_purchase <= 0:
            continue
        logger.info(f"Buying {investment.shares_to_purchase} of {investment.stock}")
        if live is True:
            try:
                result = Order(account_id=account.account_id).buy(
                    stock=investment.stock, num_shares=investment.shares_to_purchase
                )
                logger.info(f"Received result {json.dumps(result, indent=4)}")
            except Exception as exc:
                logger.exception("Uh oh problem with order", exc_info=exc)
    if live is not True:
        result = Order(account_id=account.account_id).update_status()
        logger.info(f"Received result {json.dumps(result, indent=4)}")


if __name__ == "__main__":
    args = parse_args()
    main(args.live)
