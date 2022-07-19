import types
import threading
from functools import partial
from typing import Callable

from ibapi.client import EClient
from ibapi.common import TickerId
from ibapi.contract import Contract
from ibapi.ticktype import TickTypeEnum, TickType
from ibapi.wrapper import EWrapper
from dataclasses import dataclass


class Client(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.run_thread = None

    def register(self, function_name: str, function):
        setattr(self, function_name, types.MethodType(function, self))

    def start(self, port: int, client_id: int = 1, host: str = "127.0.0.1"):
        def run_loop():
            self.run()

        self.connect(host=host, port=port, clientId=client_id)
        self.run_thread = threading.Thread(target=run_loop, daemon=True)
        self.run_thread.start()
        return self.run_thread


@dataclass
class Position:
    contract: Contract
    num_shares: float
    average_cost: float = -1


class Portfolio:
    def __init__(self):
        self.contracts = []

    def add_position(self, position: Position):
        self.contracts.append(position)


class PortfolioUpdater:
    def __init__(self, client: Client):
        self.client = client

    def update_portfolio(self, portfolio: Portfolio, callback: Callable):
        def update_positions(
            self, account: str, contract: Contract, position: float, avgCost: float
        ):
            portfolio.add_position(
                Position(contract, num_shares=position, average_cost=avgCost)
            )

        def done_updating_positions(self):
            callback(portfolio)

        self.client.register("position", update_positions)
        self.client.register("positionEnd", done_updating_positions)

        self.client.reqPositions()


class MarketDataGetter:
    def __init__(self, client: Client):
        self.client = client
        self.request_id = 1

    def request_by_contract(self, contract: Contract, callback: Callable):
        def get_result(
            self, request_id: TickerId, tick_type: TickType, value, *args, fn=""
        ):
            ticker_type = TickTypeEnum.to_str(tick_type)
            print(fn, request_id, ticker_type, value)

        for fn in [
            "tickPrice",
            "tickSize",
            "tickString",
            "tickGeneric",
            "tickEFP",
            "tickOptionComputation",
        ]:
            self.client.register(fn, partial(get_result, fn=fn))

        my_id = hash(contract)
        self.client.reqMktData(
            reqId=my_id,
            contract=contract,
            genericTickList="",
            snapshot=False,
            regulatorySnapshot=False,
            mktDataOptions=[],
        )

    def request_by_id(
        self,
        contract_id: int,
        exchange: str = "SMART",
        callback: Callable = None,
    ):
        contract = Contract()
        contract.conId = contract_id
        contract.exchange = exchange
        self.request_by_contract(contract=contract, callback=callback)

    def request_by_symbol(
        self,
        symbol: str,
        security_type="STK",
        exchange: str = "SMART",
        currency: str = "USD",
        callback: Callable = None,
    ):
        contract = Contract()
        contract.secType = security_type
        contract.symbol = symbol
        contract.exchange = exchange
        contract.currency = currency
        self.request_by_contract(contract=contract, callback=callback)
