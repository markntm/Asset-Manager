"""
schemas.py  —  Pydantic request bodies for every FinTrack endpoint.

Response shapes are plain dicts returned directly from the calculation
functions; defining Pydantic response models for them would be redundant.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


# ── Cash Flow ─────────────────────────────────────────────────────────────────

class EntryIn(BaseModel):
    """Body for income and expense cell saves."""
    year:      int
    month_idx: int
    value:     Optional[float] = None   # None → delete the stored entry


class BudgetEntryIn(BaseModel):
    """Body for per-month category budget saves (cashflow page)."""
    year:      int
    month_idx: int
    value:     Optional[float] = None


class NameIn(BaseModel):
    """Generic {name} body used by every CRUD-create endpoint."""
    name: str


class MonthlyBudgetIn(BaseModel):
    """Body for the budget-planning page's single monthly target per category."""
    monthly_budget: Optional[float] = None


# ── Net Worth ─────────────────────────────────────────────────────────────────

class NwCellIn(BaseModel):
    """
    Body for the unified cell-save endpoint.
    item_id may point to a cash account, investment holding, or asset item;
    the backend resolves which table it belongs to.
    """
    item_id:   str
    year:      int
    month_idx: int
    value:     Optional[float] = None


class HoldingIn(BaseModel):
    """Body for adding a new holding to a brokerage."""
    ticker:   str
    quantity: float = 0.0


class HoldingQtyIn(BaseModel):
    """Body for updating a holding's quantity without touching monthly values."""
    quantity: float
