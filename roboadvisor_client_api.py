# coding: utf-8

from dataclasses import dataclass
import time
import json
import requests
import logging
import pathlib
import urllib3

from typing import Dict
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(category=InsecureRequestWarning)


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

    def build_url(self, endpoint: str) -> str:
        url = self.resource_url + endpoint
        return url

    def get(self, endpoint: str, params: dict = None) -> Dict:
        return self.make_request("get", endpoint=endpoint, params=params)

    def post(self, endpoint: str, json_payload: dict = None) -> Dict:
        return self.make_request("post", endpoint=endpoint, json_payload=json_payload)

    def delete(self, endpoint: str, params: dict = None, json_payload: dict = None) -> Dict:
        return self.make_request("delete", endpoint=endpoint, params=params, json_payload=json_payload)

    def make_request(self, method: str, endpoint: str, params: dict = None, json_payload: dict = None) -> Dict:
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
        logging.info(msg="------------------------")
        logging.info(msg=f"Request Method: {method}")
        logging.info(msg="URL: {url}".format(url=url))
        logging.info(msg=f"JSON Payload: {json_payload}")
        if method == "post":
            response = requests.post(url=url, params=params, json=json_payload, verify=False)
        elif method == "get":
            response = requests.get(url=url, params=params, json=json_payload, verify=False)
        elif method == "delete":
            response = requests.delete(url=url, params=params, json=json_payload, verify=False)
        logging.info(msg=f"Response Status Code: {response.status_code}")
        logging.info(msg=f"Response Content: {response.text}")

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
                "response_request": dict(response.request.headers),
                "response_method": response.request.method,
            }

            logging.error(msg=json.dumps(obj=error_dict, indent=4))
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
    def by_symbol(cls, symbol: str, session: IBKRSession = None):
        session = cls.session if session is None else session
        params = {"symbols": symbol}
        response = session.make_request(method="get", endpoint="trsrv/stocks", params=params)
        if "error_code" in response:
            raise Exception(response)
        results = response[symbol]
        for result in results:
            for contract in result["contracts"]:
                if contract["isUS"] is True:
                    return cls(
                        symbol=symbol,
                        conid=contract["conid"],
                        exchange=contract["exchange"],
                        currency=contract["currency"]
                    )
        raise Exception(f"Could not find stock with {symbol=} on a US exchange: {results}")

    def complete_information(self):
        stock = self.get_stock_by_symbol(symbol=self.symbol)
        self.conid = stock.conid
        self.exchange = stock.exchange

    def update_latest_price(self, max_tries: int = 10):
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
            time.sleep(0.5)


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
    allocation: float = None

class Portfolio:
    session = IBKRSession()

    def __init__(self, account_id: int, session: IBKRSession = None):
        self.session = self.session if session is None else session
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
            finished = result == []
            page += 1
            for row in result:
                if row["assetClass"] != "STK":
                    continue
                symbol = row.get("ticker", row["contractDesc"])
                stock = Stock(symbol=symbol, conid=row["conid"], exchange=row["listingExchange"], currency=row["currency"])
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
                return Position(stock, num_shares=0., market_value=0.)
            raise Exception(f"You currently don't own any {sybmol=}")
        position = position[0]
        return position

    def set_allocation(self, symbol: str, allocation: float) -> Position:
        position = self.get_position(symbol, create_if_needed=True)
        position.allocation = allocation
        return position


