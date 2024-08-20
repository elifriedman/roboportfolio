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

from typing import Dict
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(category=InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class IBKRSession:
    """Serves as the Session for the Interactive Brokers API."""

    def __init__(self, url: str = "https://localhost:5000/v1/api/") -> None:
        """Initializes the `InteractiveBrokersSession` client.

        ### Overview
        ----
        The `InteractiveBrokersSession` object handles all the requests made
        for the different endpoints on the Interactive Brokers API.

        ### Parameters
        ----
        client : object
            The `InteractiveBrokersClient` Python Client.

        ### Usage:
        ----
            >>> ib_session = InteractiveBrokersSession()
        """
        self.resource_url = url
        self.logger = logging.getLogger(f"{logger.name}.session")
        self.logger.setLevel(logging.ERROR)

    def build_url(self, endpoint: str) -> str:
        url = self.resource_url + endpoint
        return url

    def get(self, endpoint: str, params: dict = None, raise_on_error: bool = True) -> Dict:
        return self.make_request("get", endpoint=endpoint, params=params, raise_on_error=raise_on_error)

    def post(self, endpoint: str, json_payload: dict = None, raise_on_error: bool = True) -> Dict:
        return self.make_request("post", endpoint=endpoint, json_payload=json_payload, raise_on_error=raise_on_error)

    def delete(
        self, endpoint: str, params: dict = None, json_payload: dict = None, raise_on_error: bool = True
    ) -> Dict:
        return self.make_request(
            "delete", endpoint=endpoint, params=params, json_payload=json_payload, raise_on_error=raise_on_error
        )

    def make_request(
        self, method: str, endpoint: str, params: dict = None, json_payload: dict = None, raise_on_error: bool = True
    ) -> Dict:
        """Handles all the requests in the library.

        ### Overview
        ---
        A central function used to handle all the requests made in the library,
        this function handles building the URL, defining Content-Type, passing
        through payloads, and handling any errors that may arise during the
        request.

        ### Parameters
        ----
        method : str
            The Request method, can be one of the following:
            ['get','post','put','delete','patch']

        endpoint : str
            The API URL endpoint, example is 'quotes'

        params : dict (optional, Default={})
            The URL params for the request.

        data : dict (optional, Default={})
        A data payload for a request.

        json_payload : dict (optional, Default={})
            A json data payload for a request

        ### Returns
        ----
        Dict:
            A Dictionary object containing the
            JSON values.
        """

        url = self.build_url(endpoint=endpoint)
        self.logger.info(msg="------------------------")
        self.logger.info(msg=f"Request Method: {method}")
        self.logger.info(msg="URL: {url}".format(url=url))
        self.logger.info(msg=f"Params: {params}")
        self.logger.info(msg=f"JSON Payload: {json_payload}")
        if method == "post":
            response = requests.post(url=url, params=params, json=json_payload, verify=False)
        elif method == "get":
            response = requests.get(url=url, params=params, json=json_payload, verify=False)
        elif method == "delete":
            response = requests.delete(url=url, params=params, json=json_payload, verify=False)
        self.logger.info(msg=f"Response Status Code: {response.status_code}")
        self.logger.info(msg=f"Response Content: {response.text}")

        if response.ok and len(response.content) > 0:
            return response.json()
        elif not response.ok:
            if len(response.content) == 0:
                response_data = ""
            else:
                try:
                    response_data = response.json()
                except:
                    response_data = response.text

            error_dict = {
                "error_code": response.status_code,
                "error_reason": response.reason,
                "response_url": response.url,
                "response_body": response_data,
                "response_request": {
                    "url": url,
                    "params": params,
                    "json": json_payload,
                    **dict(response.request.headers),
                },
                "response_method": response.request.method,
            }
            if raise_on_error:
                raise Exception(json.dumps(obj=error_dict, indent=4))

            self.logger.error(msg=json.dumps(obj=error_dict, indent=4))
            return error_dict


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
        self, symbol: str, conid: int = None, exchange: str = None, currency: str = None, session: IBKRSession = None
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

    def update_latest_price(self, max_tries: int = 10, sleep_interval: float = 0.5):
        self.session.get("/iserver/marketdata/snapshot", params={"conids": self.conid, "fields": Field.LAST_PRICE})
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

    def get_position(self, symbol: str = None, stock: Stock = None, create_if_needed: bool = False) -> Position:
        assert symbol is not None or stock is not None, f"Please provide a {symbol} or a {stock=}"
        symbol = stock.symbol if stock is not None else symbol
        position = [p for p in self.positions if p.stock.symbol == symbol]
        if len(position) == 0:
            if create_if_needed is True:
                stock = stock if stock is not None else Stock.by_symbol(symbol)
                return Position(stock, num_shares=0.0, market_value=0.0)
            raise Exception(f"You currently don't own any {symbol=}")
        position = position[0]
        return position

    def total_value(self):
        return sum([position.market_value for position in self.positions])


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
        self.initialize_ibkr_session()
        self.set_account()

    def initialize_ibkr_session(self):
        res = self.session.post("/iserver/auth/ssodh/init", json_payload={"publish": True, "compete": True})

    def set_account(self):
        result = self.session.post("/iserver/account", json_payload={"acctId": self.account_id}, raise_on_error=False)

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


@dataclass
class InvestmentPlan:
    stock: Stock
    allocation: float
    shares_to_purchase: int = 0
    shares_desired: float = 0
    offset_from_desired: float = 0


class PlanReader:
    @classmethod
    def read_plan(cls, path: str) -> InvestmentPlan:
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


def calculate_leftover_shares_to_purchase(investments: list[InvestmentPlan], money_left: float, by_offset: bool = True):
    idxs = list(range(len(investments)))
    if by_offset is True:
        idxs = sorted(idxs, key=lambda idx: investments[idx].shares_desired, reverse=True)
    else:
        random.shuffle(idxs)
    for idx in idxs:
        investment = investments[idx]
        if investment.stock.price <= money_left:
            investment.shares_to_purchase += 1
            money_left -= investment.stock.price
    return investments


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    return parser.parse_args()


def main(live: bool = False):
    account_id = "U3492785"
    account = Account(account_id=account_id)
    account.initialize()
    account.update_cash_balances()

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

    money_left = 0.0
    for investment in investments:
        position = portfolio.get_position(stock=investment.stock, create_if_needed=True)
        investment.stock.price = position.stock.update_latest_price()
        desired_value = investment.allocation * total_value
        value_to_purchase = desired_value - position.market_value
        investment.offset_from_desired = value_to_purchase
        investment.shares_desired = value_to_purchase / investment.stock.price
    total_offset = sum([i.offset_from_desired for i in investments if i.offset_from_desired > 0])
    for investment in investments:
        fraction_of_allocation = investment.offset_from_desired / total_offset
        value_to_purchase = account.usd_cash * fraction_of_allocation
        shares_to_purchase = value_to_purchase / investment.stock.price
        func = math.floor if shares_to_purchase > 0 else math.ceil
        nonfractional_num_shares = int(func(shares_to_purchase))
        investment.shares_to_purchase = nonfractional_num_shares
        leftover_money = (shares_to_purchase - nonfractional_num_shares) * position.stock.price
        leftover_money = max(leftover_money, 0)
        money_left += leftover_money

    investments = calculate_leftover_shares_to_purchase(investments, money_left=money_left, by_offset=True)
    total_shares = sum([i.shares_to_purchase for i in investments if i.shares_to_purchase > 0])
    for investment in investments:
        logger.info(portfolio.get_position(investment.stock.symbol))
        logger.info(investment)
        logger.info(
            f"offset %: {investment.offset_from_desired / total_offset*100:0.02f}, shares %: {100*investment.shares_to_purchase / total_shares:0.02f}, shares: {investment.shares_to_purchase}"
        )
        logger.info("")


if __name__ == "__main__":
    args = parse_args()
    main(args.live)
