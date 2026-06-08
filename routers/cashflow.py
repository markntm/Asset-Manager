"""
routers/cashflow.py  —  All /api/cashflow/* endpoints.

Pattern: every cell-save upserts the value, reloads the full year data,
then runs compute_month_summary so the client always receives authoritative
totals.  (The current frontend calls these fire-and-forget, but the
response payload is ready for when it starts consuming it.)
"""
from __future__ import annotations

from fastapi import APIRouter

import database.database as db
from calculations.cashflow import compute_month_summary
from schemas import BudgetEntryIn, EntryIn, NameIn

router = APIRouter(tags=["cashflow"])


# ── Year data load ────────────────────────────────────────────────────────────

@router.get("/data/{year}")
def get_cashflow_data(year: int):
    return db.get_cashflow_data(year)


# ── Income entries ────────────────────────────────────────────────────────────

@router.put("/income/{category_id}/entry")
def put_income_entry(category_id: str, body: EntryIn):
    db.upsert_income_entry(category_id, body.year, body.month_idx, body.value)
    data = db.get_cashflow_data(body.year)
    return compute_month_summary(data["income"], data["expenses"], body.month_idx)


# ── Expense entries ───────────────────────────────────────────────────────────

@router.put("/expense/subcategory/{subcategory_id}/entry")
def put_expense_entry(subcategory_id: str, body: EntryIn):
    db.upsert_expense_entry(subcategory_id, body.year, body.month_idx, body.value)
    data = db.get_cashflow_data(body.year)
    return compute_month_summary(data["income"], data["expenses"], body.month_idx)


# ── Per-month budget entries ──────────────────────────────────────────────────

@router.put("/expense/category/{category_id}/budget")
def put_budget_entry(category_id: str, body: BudgetEntryIn):
    db.upsert_budget_entry(category_id, body.year, body.month_idx, body.value)
    data = db.get_cashflow_data(body.year)
    return compute_month_summary(data["income"], data["expenses"], body.month_idx)


# ── Income category CRUD ──────────────────────────────────────────────────────

@router.post("/income/categories", status_code=201)
def post_income_category(body: NameIn):
    return db.add_income_category(body.name)


@router.delete("/income/categories/{category_id}", status_code=204)
def delete_income_category(category_id: str):
    db.delete_income_category(category_id)


# ── Expense category CRUD ─────────────────────────────────────────────────────

@router.post("/expense/categories", status_code=201)
def post_expense_category(body: NameIn):
    return db.add_expense_category(body.name)


@router.delete("/expense/categories/{category_id}", status_code=204)
def delete_expense_category(category_id: str):
    db.delete_expense_category(category_id)


# ── Subcategory CRUD ──────────────────────────────────────────────────────────

@router.post("/expense/categories/{category_id}/subcategories", status_code=201)
def post_expense_subcategory(category_id: str, body: NameIn):
    return db.add_expense_subcategory(category_id, body.name)


@router.delete("/expense/subcategories/{subcategory_id}", status_code=204)
def delete_expense_subcategory(subcategory_id: str):
    db.delete_expense_subcategory(subcategory_id)
