import dataclasses
import sys

sys.path.append("/home/eli/workspace/roboportfolio")
import pandas as pd
import os
import gradio as gr

from roboadvisor.client_api import (
    login,
    Portfolio,
    Position,
    PlanReader,
    InvestmentPlanStrategy,
    Order,
)


class Data:
    account = None


def get_account_value(account):
    account.update_cash_balances()
    return [[account.ils_cash, account.usd_cash]]


def get_investments(account):
    print("getting investments")
    portfolio = Portfolio(account_id=account.account_id)
    investments = PlanReader.update_portfolio("config/allocation.csv", portfolio)
    investments = InvestmentPlanStrategy(investments=investments).run(
        portfolio=portfolio, cash_available=account.usd_cash
    )
    return portfolio


def display(portfolio: Portfolio):
    print("displaying")
    data = [
        {make_name(k): v for k, v in dataclasses.asdict(position).items()}
        for position in portfolio.positions
    ]
    for row in data:
        stock = row["Stock"]
        row["Stock"] = stock.symbol
        row["Price"] = stock.price

    return pd.DataFrame(data)


def make_name(name):
    return name.replace("_", " ").capitalize()


with gr.Blocks() as demo:
    account_id = gr.Textbox(label="Account ID", value=os.environ.get("ACCOUNT_ID"))
    account = gr.State()
    portfolio = gr.State()
    start = gr.Button(value="Log In")
    cash_balances = gr.DataFrame(
        label="Cash Balances", headers=["ILS", "USD"], row_count=1, datatype="number"
    )

    fields = [make_name(field.name) for field in dataclasses.fields(Position)]
    fields.insert(1, "Price")
    portfolio_display = gr.DataFrame(label="Portfolio", headers=fields)
    start.click(login, inputs=[account_id], outputs=[account]).then(
        get_account_value, inputs=[account], outputs=[cash_balances], every=60
    ).then(get_investments, inputs=[account], outputs=[portfolio]).then(
        display, inputs=[portfolio], outputs=[portfolio_display]
    )

demo.launch(debug=True)
