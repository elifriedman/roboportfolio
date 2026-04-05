import csv
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

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

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET env var is required — generate one with: openssl rand -hex 32")

SESSION_TIMEOUT_SECONDS = int(float(os.getenv("SESSION_TIMEOUT_HOURS", "3")) * 3600)

ALLOCATION_PATH = Path("config/allocation.csv")
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=SESSION_TIMEOUT_SECONDS,
    same_site="strict",
    https_only=False,
)

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

def require_auth(request: Request) -> None:
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")


def require_account() -> Account:
    account = state["account"]
    if account is None:
        raise HTTPException(status_code=401, detail="No account selected")
    return account


# ── Auth & account routes ─────────────────────────────────────────────────────

@app.get("/api/auth-status")
def api_auth_status(request: Request):
    """Check whether the browser session is authenticated."""
    authenticated = bool(request.session.get("authenticated"))
    account_selected = bool(request.session.get("account_selected"))
    return {"authenticated": authenticated, "account_selected": account_selected}


@app.post("/api/login")
def api_login(req: LoginRequest, request: Request):
    """Log in to IBKR via Playwright using the provided credentials."""
    if request.session.get("authenticated"):
        return {
            "ok": True,
            "already_logged_in": True,
            "account_selected": bool(request.session.get("account_selected")),
        }

    success = login_to_ibkr(req.username, req.password)
    if not success:
        raise HTTPException(status_code=401, detail="Login failed — check credentials or approve the 2FA prompt")
    request.session["authenticated"] = True
    request.session["account_selected"] = False
    try:
        _session.post(
            "/iserver/auth/ssodh/init",
            json_payload={"publish": True, "compete": True},
        )
    except RequestException:
        pass
    return {"ok": True, "already_logged_in": False, "account_selected": False}


@app.get("/api/accounts")
def api_accounts(_: None = Depends(require_auth)):
    """Return list of available IBKR accounts."""
    return _session.get("/portfolio/accounts")


@app.post("/api/accounts/select")
def api_select_account(req: SelectAccountRequest, request: Request, _: None = Depends(require_auth)):
    """Select an account and initialise the Account object."""
    account = Account(account_id=req.account_id, session=_session)
    account.set_account()
    account.update_cash_balances()
    account.keep_connection_alive()
    state["account"] = account
    request.session["account_selected"] = True
    return {"ok": True}


# ── Cash routes ───────────────────────────────────────────────────────────────

@app.get("/api/cash")
def api_cash(_: None = Depends(require_auth)):
    account = require_account()
    account.update_cash_balances()
    return {
        "ils": account.ils_cash,
        "usd": account.usd_cash,
        "usd_tradable": account.usd_tradable_cash,
    }


@app.post("/api/convert-ils")
def api_convert_ils(req: ConvertILSRequest, _: None = Depends(require_auth)):
    account = require_account()
    account.update_cash_balances()
    if req.amount is None:
        account.convert_all_ils_to_usd()
    else:
        account.convert_to_usd(req.amount)
    return {"ok": True}


# ── Allocation routes ─────────────────────────────────────────────────────────

@app.get("/api/allocation")
def api_get_allocation(_: None = Depends(require_auth)):
    if not ALLOCATION_PATH.exists():
        return []
    with open(ALLOCATION_PATH) as f:
        dr = csv.DictReader(f)
        return [{"stock": row["stock"], "allocation": float(row["allocation"])} for row in dr]


@app.put("/api/allocation")
def api_put_allocation(rows: list[AllocationRow], _: None = Depends(require_auth)):
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
def api_portfolio(_: None = Depends(require_auth)):
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
def api_orders(req: OrderRequest, _: None = Depends(require_auth)):
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
