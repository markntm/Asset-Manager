"""Income, Expenses, Budget-Entry Functions"""

from collections import defaultdict
from sqlalchemy import select
from database.base import (SessionLocal, add_child, add_root, cells, delete_child,
                           delete_root, require_child, require_root, roots, upsert_cell)
from database.models import (BudgetEntry, ExpenseCategory, ExpenseEntry,
                             ExpenseSubcategory, IncomeCategory, IncomeEntry)


def get_cashflow_data(user_id: str, year: int) -> dict:
    with SessionLocal.begin() as s:
        inc = roots(s, IncomeCategory, user_id)
        inc_vals = cells(s, IncomeEntry, "category_id", [c.id for c in inc], year)

        exp = roots(s, ExpenseCategory, user_id)
        exp_ids = [c.id for c in exp]
        subs = s.scalars(select(ExpenseSubcategory)
                         .where(ExpenseSubcategory.category_id.in_(exp_ids))
                         .order_by(ExpenseSubcategory.name)).all()
        sub_vals = cells(s, ExpenseEntry, "subcategory_id", [sc.id for sc in subs], year)
        bud_vals = cells(s, BudgetEntry, "category_id", exp_ids, year)

        subs_by_cat = defaultdict(list)
        for sc in subs:
            subs_by_cat[sc.category_id].append({"id": sc.id, "name": sc.name, "values": sub_vals[sc.id]})

        return {
            "income": [{"id": c.id, "name": c.name, "values": inc_vals[c.id]} for c in inc],
            "expenses": [{"id": c.id, "name": c.name, "budget": bud_vals[c.id],
                          "subcategories": subs_by_cat[c.id]} for c in exp],
        }


# ── CRUD ──
def add_income_category(user_id, name):
    return add_root(IncomeCategory, user_id, name)

def delete_income_category(user_id, category_id):
    delete_root(IncomeCategory, user_id, category_id)

def add_expense_category(user_id, name):
    return add_root(ExpenseCategory, user_id, name)

def delete_expense_category(user_id, category_id):
    delete_root(ExpenseCategory, user_id, category_id)

def add_expense_subcategory(user_id, category_id, name):
    return add_child(user_id, ExpenseSubcategory, "category_id", ExpenseCategory, category_id, name=name)

def delete_expense_subcategory(user_id, subcategory_id):
    delete_child(user_id, ExpenseSubcategory, "category_id", ExpenseCategory, subcategory_id)


# ── Cell upserts ──
def upsert_income_entry(user_id, category_id, year, month_idx, value):
    with SessionLocal.begin() as s:
        require_root(s, IncomeCategory, category_id, user_id)
        upsert_cell(s, IncomeEntry, "category_id", category_id, year, month_idx, value)

def upsert_expense_entry(user_id, subcategory_id, year, month_idx, value):
    with SessionLocal.begin() as s:
        require_child(s, ExpenseSubcategory, "category_id", ExpenseCategory, subcategory_id, user_id)
        upsert_cell(s, ExpenseEntry, "subcategory_id", subcategory_id, year, month_idx, value)

def upsert_budget_entry(user_id, category_id, year, month_idx, value):
    with SessionLocal.begin() as s:
        require_root(s, ExpenseCategory, category_id, user_id)
        upsert_cell(s, BudgetEntry, "category_id", category_id, year, month_idx, value)
