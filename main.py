"""
main.py — FinTrack FastAPI Application
Handles page serving, all API routes, and Pydantic I/O models.
Database operations are delegated to database.py (implemented next step).
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import uvicorn
import os

import database.database as db

# ═══════════════════════════════════════════════════════════════════
#  APP SETUP
# ═══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create SQLite tables on first run."""
    db.init_db()
    yield

app = FastAPI(
    title       = "FinTrack API",
    version     = "1.0.0",
    description = "Personal finance tracker — cash flow, net worth, and allocation",
    lifespan    = lifespan
)

# CORS — open for local dev; lock down origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")

# ═══════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════

# ── Shared ──────────────────────────────────────────────────────────
class OkResponse(BaseModel):
    ok:      bool = True
    message: str  = "success"


# ── Cash Flow — request bodies ───────────────────────────────────────
class IncomeCategoryIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100,
                      examples=["Job 1", "Freelance"])

class IncomeCategoryUpdateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class ExpenseCategoryIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100,
                      examples=["Dining", "Rent"])
    type: str = Field(..., pattern="^(discretionary|fixed|one-time)$")

class ExpenseCategoryUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[str] = Field(None, pattern="^(discretionary|fixed|one-time)$")

class CashFlowCellIn(BaseModel):
    table:     str            = Field(..., pattern="^(income|expense)$")
    row_id:    str            = Field(..., description="Category UUID")
    year:      int            = Field(..., ge=2000, le=2100)
    month_idx: int            = Field(..., ge=0, le=11, description="0 = Jan, 11 = Dec")
    value:     Optional[float] = Field(None, description="null clears the cell")


# ── Cash Flow — response bodies ──────────────────────────────────────
class IncomeCategoryOut(BaseModel):
    id:   str
    name: str

class ExpenseCategoryOut(BaseModel):
    id:   str
    name: str
    type: str

class CashFlowRowOut(BaseModel):
    id:     str
    name:   str
    values: Dict[str, float] = {}   # {"0": 5000, "1": 5200, …}

class ExpenseRowOut(CashFlowRowOut):
    type: str

class CashFlowYearOut(BaseModel):
    year:     int
    income:   List[CashFlowRowOut]
    expenses: List[ExpenseRowOut]


# ── Net Worth — request bodies ───────────────────────────────────────
class AccountIn(BaseModel):
    group_id: str = Field(..., pattern="^(savings|investments|assets)$")
    name:     str = Field(..., min_length=1, max_length=100,
                          examples=["Capital One HYSA", "VOO ETF", "Home Value"])

class AccountUpdateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class NetWorthCellIn(BaseModel):
    item_id:   str
    year:      int            = Field(..., ge=2000, le=2100)
    month_idx: int            = Field(..., ge=0, le=11)
    value:     Optional[float] = Field(None, description="null clears the cell")


# ── Net Worth — response bodies ──────────────────────────────────────
class AccountOut(BaseModel):
    id:       str
    name:     str
    group_id: str

class AccountsStructureOut(BaseModel):
    savings:     List[AccountOut]
    investments: List[AccountOut]
    assets:      List[AccountOut]

class NetWorthRowOut(BaseModel):
    id:       str
    name:     str
    group_id: str
    values:   Dict[str, float] = {}   # {"0": 5000, "1": 5200, …}

class NetWorthYearOut(BaseModel):
    year:     int
    accounts: AccountsStructureOut
    rows:     List[NetWorthRowOut]


# ── Dashboard — response body ────────────────────────────────────────
class AccountSnapshotOut(BaseModel):
    name:         str
    institution:  str
    type:         str             # "savings" | "investments" | "assets"
    balance:      float
    pct_of_total: float
    mom_change:   Optional[float] = None

class DashboardSummaryOut(BaseModel):
    net_worth:         float
    total_cash:        float
    total_investments: float
    monthly_cashflow:  float
    savings_rate:      float                  # percentage, e.g. 32.5
    nw_mom_change:     Optional[float] = None
    nw_mom_pct:        Optional[float] = None
    net_worth_trend:   List[Optional[float]]  # 12 values; null = no data that month
    allocation:        Dict[str, float]       # {savings, investments, assets}
    accounts:          List[AccountSnapshotOut]

# ═══════════════════════════════════════════════════════════════════
#  HTML PAGE ROUTES
#  Serve each page; update nav hrefs in HTML from *.html to these paths
# ═══════════════════════════════════════════════════════════════════

@app.get("/", response_class=FileResponse, include_in_schema=False)
async def page_dashboard():
    return FileResponse(os.path.join(TEMPLATES, "dashboard.html"))

@app.get("/cashflow", response_class=FileResponse, include_in_schema=False)
async def page_cashflow():
    return FileResponse(os.path.join(TEMPLATES, "cashflow.html"))

@app.get("/networth", response_class=FileResponse, include_in_schema=False)
async def page_networth():
    return FileResponse(os.path.join(TEMPLATES, "networth.html"))

# ═══════════════════════════════════════════════════════════════════
#  DASHBOARD  /api/dashboard
# ═══════════════════════════════════════════════════════════════════

@app.get(
    "/api/dashboard/summary",
    response_model=DashboardSummaryOut,
    tags=["Dashboard"],
    summary="Aggregated snapshot for the dashboard page",
)
async def get_dashboard_summary():
    """
    Pulls from both the net worth and cash flow tables to return
    the current net worth, monthly cash flow, savings rate, 12-month
    trend, group allocation, and per-account overview.
    """
    return db.get_dashboard_summary()

# ═══════════════════════════════════════════════════════════════════
#  CASH FLOW  /api/cashflow
# ═══════════════════════════════════════════════════════════════════

@app.get(
    "/api/cashflow/data/{year}",
    response_model=CashFlowYearOut,
    tags=["Cash Flow"],
    summary="All income + expense categories with monthly values for a year",
)
async def get_cashflow_year(year: int):
    """
    Called by cashflow.html on page load and on year-selector change.
    Returns every category row with its 12-slot values dict.
    """
    return db.get_cashflow_year(year)


# ── Income categories ────────────────────────────────────────────────

@app.post(
    "/api/cashflow/categories/income",
    response_model=IncomeCategoryOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Cash Flow"],
    summary="Create a new income category",
)
async def create_income_category(body: IncomeCategoryIn):
    return db.create_income_category(body.name)


@app.put(
    "/api/cashflow/categories/income/{category_id}",
    response_model=IncomeCategoryOut,
    tags=["Cash Flow"],
    summary="Rename an income category",
)
async def update_income_category(category_id: str, body: IncomeCategoryUpdateIn):
    result = db.update_income_category(category_id, body.name)
    if not result:
        raise HTTPException(status_code=404, detail="Income category not found")
    return result


@app.delete(
    "/api/cashflow/categories/income/{category_id}",
    response_model=OkResponse,
    tags=["Cash Flow"],
    summary="Delete an income category and all its cell values",
)
async def delete_income_category(category_id: str):
    if not db.delete_income_category(category_id):
        raise HTTPException(status_code=404, detail="Income category not found")
    return OkResponse(message=f"Income category {category_id} deleted")


# ── Expense categories ───────────────────────────────────────────────

@app.post(
    "/api/cashflow/categories/expense",
    response_model=ExpenseCategoryOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Cash Flow"],
    summary="Create a new expense category",
)
async def create_expense_category(body: ExpenseCategoryIn):
    return db.create_expense_category(body.name, body.type)


@app.put(
    "/api/cashflow/categories/expense/{category_id}",
    response_model=ExpenseCategoryOut,
    tags=["Cash Flow"],
    summary="Update an expense category name and/or type",
)
async def update_expense_category(category_id: str, body: ExpenseCategoryUpdateIn):
    result = db.update_expense_category(category_id, body.name, body.type)
    if not result:
        raise HTTPException(status_code=404, detail="Expense category not found")
    return result


@app.delete(
    "/api/cashflow/categories/expense/{category_id}",
    response_model=OkResponse,
    tags=["Cash Flow"],
    summary="Delete an expense category and all its cell values",
)
async def delete_expense_category(category_id: str):
    if not db.delete_expense_category(category_id):
        raise HTTPException(status_code=404, detail="Expense category not found")
    return OkResponse(message=f"Expense category {category_id} deleted")


# ── Cell update (income or expense) ─────────────────────────────────

@app.put(
    "/api/cashflow/cells",
    response_model=OkResponse,
    tags=["Cash Flow"],
    summary="Upsert a single cash flow cell (income or expense)",
)
async def upsert_cashflow_cell(body: CashFlowCellIn):
    """
    Called on `onblur` from every editable cell in cashflow.html.
    Pass value=null to clear/delete a cell.
    """
    db.upsert_cashflow_cell(
        table     = body.table,
        row_id    = body.row_id,
        year      = body.year,
        month_idx = body.month_idx,
        value     = body.value,
    )
    return OkResponse()

# ═══════════════════════════════════════════════════════════════════
#  NET WORTH  /api/networth
# ═══════════════════════════════════════════════════════════════════

@app.get(
    "/api/networth/accounts",
    response_model=AccountsStructureOut,
    tags=["Net Worth"],
    summary="Account structure (no values) for building the table skeleton",
)
async def get_accounts_structure():
    """
    Returns all accounts grouped under savings / investments / assets.
    Accounts are shared across all years — only values are per-year.
    Called once on page load before the year-specific data is fetched.
    """
    return db.get_accounts_structure()


@app.get(
    "/api/networth/data/{year}",
    response_model=NetWorthYearOut,
    tags=["Net Worth"],
    summary="Account structure + all balance values for a given year",
)
async def get_networth_year(year: int):
    """
    Called by networth.html on page load and on year-selector change.
    Returns the full account tree plus every filled-in monthly balance.
    """
    return db.get_networth_year(year)


@app.post(
    "/api/networth/accounts",
    response_model=AccountOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Net Worth"],
    summary="Add a new account to a group (appears in all years)",
)
async def create_account(body: AccountIn):
    return db.create_account(body.group_id, body.name)


@app.put(
    "/api/networth/accounts/{account_id}",
    response_model=AccountOut,
    tags=["Net Worth"],
    summary="Rename an account",
)
async def update_account(account_id: str, body: AccountUpdateIn):
    result = db.update_account(account_id, body.name)
    if not result:
        raise HTTPException(status_code=404, detail="Account not found")
    return result


@app.delete(
    "/api/networth/accounts/{account_id}",
    response_model=OkResponse,
    tags=["Net Worth"],
    summary="Delete an account and all its values across all years",
)
async def delete_account(account_id: str):
    if not db.delete_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return OkResponse(message=f"Account {account_id} deleted")


@app.put(
    "/api/networth/cells",
    response_model=OkResponse,
    tags=["Net Worth"],
    summary="Upsert a single net worth balance cell",
)
async def upsert_networth_cell(body: NetWorthCellIn):
    """
    Called on `onblur` from every editable cell in networth.html.
    Pass value=null to clear/delete a cell.
    """
    db.upsert_networth_cell(
        item_id   = body.item_id,
        year      = body.year,
        month_idx = body.month_idx,
        value     = body.value,
    )
    return OkResponse()

# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Link: " + "http://127.0.0.1:8000/")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


