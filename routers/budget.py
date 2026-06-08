"""
routers/budget.py  —  /api/budget/* endpoints.

The budget-planning page works with a single monthly_budget figure per
expense category (not per month), stored separately from the cashflow
page's per-month budget column.
"""
from __future__ import annotations

from fastapi import APIRouter

import database.database as db
from schemas import MonthlyBudgetIn

router = APIRouter(tags=["budget"])


@router.get("/categories")
def get_budget_categories():
    return {"categories": db.get_budget_categories()}


@router.put("/category/{category_id}")
def put_budget_category(category_id: str, body: MonthlyBudgetIn):
    db.upsert_budget_target(category_id, body.monthly_budget)
    return {"ok": True}
