import csv
import time
import types
import threading
from functools import partial
from typing import Callable, Union, List, Dict, Any

from ibapi.client import EClient
from ibapi.common import TickerId, MarketDataTypeEnum
from ibapi.contract import Contract
from ibapi.ticktype import TickTypeEnum, TickType
from ibapi.wrapper import EWrapper
from dataclasses import dataclass


class Client(EWrapper, EClient):
    def __init__(self, port: int):
        EClient.__init__(self, self)
        self.run_thread = None
        self.initialize_market_data_handlers()
        self.start(port=port)
        self.market_data_functions = {}

    def register(self, function_name: str, function: Callable):
        setattr(self, function_name, types.MethodType(function, self))

    def start(self, port: int, client_id: int = 1, host: str = "127.0.0.1"):
        def run_loop():
            self.run()

        self.connect(host=host, port=port, clientId=client_id)
        self.run_thread = threading.Thread(target=run_loop, daemon=True)
        self.run_thread.start()
        return self.run_thread

    def register_market_data_callback(self, request_id: int, function: Callable):
        self.market_data_functions[request_id] = function

    def initialize_market_data_handlers(self):
        def handle_market_data(self, request_id: int, *args, **kwargs):
            if request_id in self.market_data_functions:
                self.market_data_functions[request_id](*args, **kwargs)

        for fn in [
            "tickPrice",
            "tickSize",
            "tickString",
            "tickGeneric",
            "tickEFP",
            "tickOptionComputation",
        ]:
            self.register(function_name=fn, function=handle_market_data)


@dataclass
class Position:
    contract: Contract
    num_shares: float
    average_cost: float = -1
    current_price: float = None


class Portfolio:
    def __init__(self):
        self.positions = []

    def add_position(self, position: Position):
        self.positions.append(position)


class PortfolioUpdater:
    def __init__(self, client: Client):
        self.client = client

    def update_portfolio(self, portfolio: Portfolio, callback: Callable):
        def add_positions(positions: List[Position]):
            for position in positions:
                portfolio.add_position(position)
            callback(portfolio)

        def update_portfolio(positions):
            self.get_price_for_positions(positions=positions, callback=add_positions)

        self.get_all_positions(callback=update_portfolio)

    def get_all_positions(self, callback: Callable):
        positions = []

        def update_positions(
            self, account: str, contract: Contract, position: float, avgCost: float
        ):
            positions.append(
                Position(contract, num_shares=position, average_cost=avgCost)
            )

        def done_updating_positions(self):
            callback(positions)

        self.client.register("position", update_positions)
        self.client.register("positionEnd", done_updating_positions)

        self.client.reqPositions()

    def get_price_for_position(self, position: Position, callback: Callable):
        simple_contract = ContractBuilder.from_id(position.contract.conId)

        def get_price(contract: Contract, tick_type_str: str, value: float):
            if tick_type_str == "LAST" or tick_type_str == "CLOSE":
                position.current_price = value
                MarketDataGetter.cancel_contract_request(contract=contract)
                callback(position)

        MarketDataGetter(self.client).request_price_by_contract(
            contract=simple_contract, callback=get_price
        )

    def get_price_for_positions(self, positions: List[Position], callback: Callable):
        positions_received = []

        def all_positions_retrieved(position: Position):
            positions_received.append(position)
            if len(positions_received) == len(positions):
                callback(positions_received)

        for position in positions:
            self.get_price_for_position(
                position=position, callback=all_positions_retrieved
            )


class ContractBuilder:
    DEFAULT_EXCHANGE = "SMART"
    DEFAULT_CURRENCY = "USD"

    @classmethod
    def from_id(cls, contract_id: int, exchange: str = DEFAULT_EXCHANGE):
        contract = Contract()
        contract.conId = contract_id
        contract.exchange = exchange
        return contract

    @classmethod
    def from_symbol(
        cls,
        symbol: str,
        security_type: str = "STK",
        exchange: str = DEFAULT_EXCHANGE,
        currency: str = DEFAULT_CURRENCY,
        **kwargs,
    ) -> Contract:
        contract = Contract()
        contract.secType = security_type
        contract.symbol = symbol
        contract.exchange = exchange
        contract.currency = currency
        for k, v in kwargs.items():
            setattr(contract, k, v)
        return contract


class MarketDataGetter:
    def __init__(self, client: Client):
        self.client = client
        self.request_id = 1

    def get_id_from_contract(self, contract: Contract) -> int:
        my_id = int(hash(contract) % 2**15)
        return my_id

    def request_price_by_contract(
        self, contract: Contract, callback: Callable, timeout: float = 10.0
    ):
        my_id = self.get_id_from_contract(contract=contract)

        def get_result(tick_type: TickType, value, *args):
            tick_type_str = TickTypeEnum.to_str(tick_type)
            # if tick_type == TickTypeEnum.LAST or tick_type == TickTypeEnum.CLOSE:
            callback(contract, tick_type_str, value)
            # self.cancel_contract_request(contract=contract)

        self.client.register_market_data_callback(request_id=my_id, function=get_result)
        self.client.reqMarketDataType(MarketDataTypeEnum.DELAYED_FROZEN)
        self.client.reqMktData(
            reqId=my_id,
            contract=contract,
            genericTickList="",
            snapshot=False,
            regulatorySnapshot=False,
            mktDataOptions=[],
        )

    def cancel_contract_request(self, contract: Contract):
        my_id = self.get_id_from_contract(contract=contract)
        self.client.cancelMktData(my_id)


@dataclass
class Investment:
    symbol: str
    allocation: float


class Plan:
    def __init__(self):
        self.investments: List[Investment] = []

    def add_investment(self, investment: Investment):
        if investment not in self.investments:
            self.investments.append(investment)


class PlanReader:
    @classmethod
    def read_plan(cls, path: str) -> Plan:
        plan = Plan()
        rows = cls._load_file(path)
        for row in rows:
            plan.add_investment(Investment(row["stock"], row["allocation"]))
        return Plan

    @classmethod
    def _load_file(cls, path: str) -> List[Dict[Any, Any]]:
        with open(path) as f:
            dr = csv.DictReader(f)
            return [row for row in dr]


if __name__ == "__main__":
    PORT = 8888
    client = Client(port=PORT)
    time.sleep(0.5)
    p = Portfolio()
    PortfolioUpdater(client).update_portfolio(
        portfolio=p, callback=lambda *args: print(args)
    )
    # md = MarketDataGetter(client)
