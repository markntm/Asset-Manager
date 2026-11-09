"""
routers/budget.py  —  /api/budget/* endpoints.

The budget-planning page works with a single monthly_budget figure per
expense category (not per month), stored separately from the cashflow
page's per-month budget column.
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from auth import current_user_id
from calculations.cashflow import expense_category_total
from database import budget as db
from database import cashflow as cf_db
from schemas import MonthlyBudgetIn

router = APIRouter(tags=["budget"])


@router.get("/categories")
def get_budget_categories(
        year:  int | None = Query(None, ge=2000, le=2100),
        month: int | None = Query(None, ge=1, le=12),
        user_id: str = Depends(current_user_id),
):
    if year is None or month is None:
        now = datetime.now(ZoneInfo("Pacific/Honolulu"))
        year, month = now.year, now.month
    cats = db.get_budget_categories(user_id)
    spent = {c["id"]: expense_category_total(c, month - 1)
             for c in cf_db.get_cashflow_data(user_id, year)["expenses"]}
    for c in cats:
        c["spent"] = round(spent.get(c["id"], 0.0), 2)
    return {"categories": cats, "year": year, "month": month}


@router.put("/category/{category_id}")
def put_budget_category(category_id: str, body: MonthlyBudgetIn, user_id: str = Depends(current_user_id)):
    db.upsert_budget_target(user_id, category_id, body.monthly_budget)
    return {"ok": True}
