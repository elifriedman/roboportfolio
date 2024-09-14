import dataclasses
import sys

sys.path.append("/home/eli/workspace/roboportfolio")
import pandas as pd
import os
import gradio as gr

from roboadvisor.client_api import (
    Account,
    OrderException,
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
    investments = InvestmentPlanStrategy(
        account_id=account.account_id, investments=investments
    ).run(portfolio=portfolio, cash_available=account.usd_cash)
    return portfolio, investments


fields = [
    "Stock",
    "Price",
    "# Shares",
    "Allocation (%)",
    "Desired Value ($)",
    "# Shares Needed",
    "# Shares to Buy",
]


def display(portfolio: Portfolio, account: Account):
    print("displaying")
    data = []
    for position in portfolio.positions:
        stock = position.stock
        row = {}
        row["Stock"] = stock.symbol
        row["Price"] = stock.price
        row["# Shares"] = position.num_shares
        row["Allocation (%)"] = position.allocation * 100 if position.allocation is not None else 0
        row["Desired Value ($)"] = position.shares_desired * stock.price
        row["# Shares Needed"] = position.shares_desired
        row["# Shares to Buy"] = position.shares_to_purchase
        data.append(row)

    account_value = [
        {
            "Invested ($)": portfolio.total_value(),
            "Invested + Cash ($)": portfolio.total_value() + account.usd_cash,
        }
    ]

    return pd.DataFrame(account_value), pd.DataFrame(data)


def make_name(name):
    return name.replace("_", " ").capitalize()


def perform_login(account_id):
    gr.Info("Logging in...")
    result = login(account_id=account_id)
    return result


def order(investments: InvestmentPlanStrategy, simulated: bool):
    live = not simulated
    gr.Info(f"Ordering {'Live' if live is True else 'Simulated'} {live=}")
    try:
        results = investments.execute_orders(live=live)
        return results
    except OrderException as exc:
        gr.Error(f"Order failed: {exc=}")


with gr.Blocks() as demo:
    account_id = gr.Textbox(label="Account ID", value=os.environ.get("ACCOUNT_ID"))
    account = gr.State()
    portfolio = gr.State()
    investments = gr.State()
    start = gr.Button(value="Log In")
    cash_balances = gr.DataFrame(
        label="Cash Balances", headers=["ILS", "USD"], row_count=1, datatype="number"
    )
    portfolio_value = gr.DataFrame(label="Portfolio Value", headers=["Invested", "Invested+Cash"])
    portfolio_display = gr.DataFrame(label="Portfolio", headers=fields)
    simulated = gr.Checkbox(label="Simulate Order", value=False)
    order_button = gr.Button(value="Order")
    outputs = gr.Textbox()
    start.click(perform_login, inputs=[account_id], outputs=[account]).then(
        get_account_value, inputs=[account], outputs=[cash_balances], every=60
    ).then(get_investments, inputs=[account], outputs=[portfolio, investments]).then(
        display, inputs=[portfolio, account], outputs=[portfolio_value, portfolio_display]
    )
    order_button.click(order, inputs=[investments, simulated], outputs=[outputs])

demo.launch(debug=True)
