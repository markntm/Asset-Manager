"""Budget Tracking"""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from database.base import SessionLocal, require_root
from database.models import BudgetTarget, ExpenseCategory


def get_budget_categories(user_id: str) -> list[dict]:
    with SessionLocal.begin() as s:
        rows = s.execute(
            select(ExpenseCategory.id, ExpenseCategory.name, BudgetTarget.monthly_budget)
            .outerjoin(BudgetTarget, BudgetTarget.category_id == ExpenseCategory.id)
            .where(ExpenseCategory.user_id == user_id)
            .order_by(ExpenseCategory.created_at)
        ).all()
        return [{"id": r.id, "name": r.name,
                 "monthly_budget": float(r.monthly_budget) if r.monthly_budget is not None else None}
                for r in rows]


def upsert_budget_target(user_id: str, category_id: str, monthly_budget) -> None:
    with SessionLocal.begin() as s:
        require_root(s, ExpenseCategory, category_id, user_id)
        if monthly_budget is None:
            s.execute(delete(BudgetTarget).where(BudgetTarget.category_id == category_id))
            return
        stmt = insert(BudgetTarget).values(category_id=category_id, monthly_budget=monthly_budget)
        s.execute(stmt.on_conflict_do_update(
            index_elements=["category_id"], set_={"monthly_budget": stmt.excluded.monthly_budget}))
