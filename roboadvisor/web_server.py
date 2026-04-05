import csv
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from roboadvisor.client_api import (
    Account,
    InvestmentPlanStrategy,
    Order,
    OrderException,
    Portfolio,
    PlanReader,
)
from roboadvisor.ibkr_session import IBKRSession, RequestException
from roboadvisor.initial_login import login_to_ibkr

app = FastAPI()

ALLOCATION_PATH = Path("config/allocation.csv")
STATIC_DIR = Path(__file__).parent / "static"

# Single-user global state
_session = IBKRSession()
state: dict = {
    "account": None,
    "investments": None,
}


# ── Pydantic models ───────────────────────────────────────────────────────────

class SelectAccountRequest(BaseModel):
    account_id: str


class ConvertILSRequest(BaseModel):
    amount: Optional[float] = None


class AllocationRow(BaseModel):
    stock: str
    allocation: float


class LoginRequest(BaseModel):
    username: str
    password: str


class OrderRequest(BaseModel):
    live: bool = False
    symbol: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def require_account() -> Account:
    account = state["account"]
    if account is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return account


# ── Auth & account routes ─────────────────────────────────────────────────────

@app.get("/api/auth-status")
def api_auth_status():
    """Check whether the IBKR gateway session is already authenticated."""
    try:
        _session.post(
            "/iserver/auth/ssodh/init",
            json_payload={"publish": True, "compete": True},
            raise_on_error=True,
        )
        _session.get("/portfolio/accounts", raise_on_error=True)
        return {"authenticated": True}
    except Exception:
        return {"authenticated": False}


@app.post("/api/login")
def api_login(req: LoginRequest):
    """Log in to IBKR via Playwright using the provided credentials."""
    # Check if already authenticated
    if api_auth_status()["authenticated"]:
        return {"ok": True, "already_logged_in": True}

    success = login_to_ibkr(req.username, req.password)
    if not success:
        raise HTTPException(status_code=401, detail="Login failed — check credentials or approve the 2FA prompt")
    try:
        _session.post(
            "/iserver/auth/ssodh/init",
            json_payload={"publish": True, "compete": True},
        )
    except RequestException:
        pass
    return {"ok": True, "already_logged_in": False}


@app.get("/api/accounts")
def api_accounts():
    """Return list of available IBKR accounts."""
    return _session.get("/portfolio/accounts")


@app.post("/api/accounts/select")
def api_select_account(req: SelectAccountRequest):
    """Select an account and initialise the Account object."""
    account = Account(account_id=req.account_id, session=_session)
    account.set_account()
    account.update_cash_balances()
    account.keep_connection_alive()
    state["account"] = account
    return {"ok": True}


# ── Cash routes ───────────────────────────────────────────────────────────────

@app.get("/api/cash")
def api_cash():
    account = require_account()
    account.update_cash_balances()
    return {
        "ils": account.ils_cash,
        "usd": account.usd_cash,
        "usd_tradable": account.usd_tradable_cash,
    }


@app.post("/api/convert-ils")
def api_convert_ils(req: ConvertILSRequest):
    account = require_account()
    account.update_cash_balances()
    if req.amount is None:
        account.convert_all_ils_to_usd()
    else:
        account.convert_to_usd(req.amount)
    return {"ok": True}


# ── Allocation routes ─────────────────────────────────────────────────────────

@app.get("/api/allocation")
def api_get_allocation():
    if not ALLOCATION_PATH.exists():
        return []
    with open(ALLOCATION_PATH) as f:
        dr = csv.DictReader(f)
        return [{"stock": row["stock"], "allocation": float(row["allocation"])} for row in dr]


@app.put("/api/allocation")
def api_put_allocation(rows: list[AllocationRow]):
    total = sum(r.allocation for r in rows)
    if abs(total - 1.0) > 0.001:
        raise HTTPException(
            status_code=400,
            detail=f"Allocations must sum to 1.0, got {total:.4f}",
        )
    ALLOCATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ALLOCATION_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["stock", "allocation"])
        for row in rows:
            writer.writerow([row.stock, row.allocation])
    return {"ok": True}


# ── Portfolio route ───────────────────────────────────────────────────────────

@app.get("/api/portfolio")
def api_portfolio():
    account = require_account()
    account.update_cash_balances()

    portfolio = Portfolio(account_id=account.account_id, session=account.session)
    investments = PlanReader.update_portfolio(str(ALLOCATION_PATH), portfolio)
    strategy = InvestmentPlanStrategy(
        account_id=account.account_id, investments=investments
    ).run(portfolio=portfolio, cash_available=account.usd_cash)

    state["investments"] = strategy

    total_invested = portfolio.total_value()
    grand_total = total_invested + account.usd_cash

    positions = []
    for pos in portfolio.positions:
        if pos.stock.price is None:
            raise ValueError(f"Could not get stock price for {pos.stock.price}")
        current_value = pos.market_value
        planned_value = current_value + pos.shares_to_purchase * pos.stock.price
        positions.append({
            "symbol": pos.stock.symbol,
            "price": pos.stock.price,
            "num_shares": pos.num_shares,
            "current_value": current_value,
            "current_pct": current_value / grand_total if grand_total > 0 else 0,
            "ideal_pct": pos.allocation,
            "shares_desired": pos.shares_desired,
            "shares_to_purchase": pos.shares_to_purchase,
            "value_to_purchase": pos.value_to_purchase,
            "planned_value": planned_value,
            "planned_pct": planned_value / grand_total if grand_total > 0 else 0,
        })

    return {
        "total_invested": total_invested,
        "total_with_cash": grand_total,
        "usd_cash": account.usd_cash,
        "positions": positions,
    }


# ── Orders route ──────────────────────────────────────────────────────────────

@app.post("/api/orders")
def api_orders(req: OrderRequest):
    account = require_account()
    strategy = state["investments"]
    if strategy is None:
        raise HTTPException(
            status_code=400, detail="Portfolio not loaded — call /api/portfolio first"
        )

    order = Order(account_id=account.account_id)

    if req.symbol:
        try:
            investment = next(
                i for i in strategy.investments if i.stock.symbol == req.symbol
            )
        except StopIteration:
            raise HTTPException(status_code=404, detail=f"Symbol {req.symbol} not in plan")
        if investment.shares_to_purchase <= 0:
            raise HTTPException(
                status_code=400, detail=f"No shares to purchase for {req.symbol}"
            )
        order_dict = order.make_order("BUY", investment.stock, investment.shares_to_purchase)
        try:
            result = order.order(order_dict, live=req.live)
        except OrderException as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return {"ok": True, "results": [result]}
    else:
        try:
            results = strategy.execute_orders(live=req.live)
        except OrderException as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return {"ok": True, "results": results}


# ── Static files ──────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
