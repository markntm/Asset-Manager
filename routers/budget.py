"""
routers/budget.py  —  /api/budget/* endpoints.

The budget-planning page works with a single monthly_budget figure per
expense category (not per month), stored separately from the cashflow
page's per-month budget column.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import current_user_id
from database import budget as db
from schemas import MonthlyBudgetIn

router = APIRouter(tags=["budget"])


@router.get("/categories")
def get_budget_categories(user_id: str = Depends(current_user_id)):
    return {"categories": db.get_budget_categories(user_id)}


@router.put("/category/{category_id}")
def put_budget_category(category_id: str, body: MonthlyBudgetIn, user_id: str = Depends(current_user_id)):
    db.upsert_budget_target(user_id, category_id, body.monthly_budget)
    return {"ok": True}
