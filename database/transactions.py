"""Transactions"""

from sqlalchemy import select
from database.base import (NotFound, SessionLocal, delete_root, require_child,
                           require_root, roots)
from database.models import (CashInstitution, ExpenseCategory, ExpenseSubcategory,
                             IncomeCategory, Transaction)


def _row(t) -> dict:
    return {"id": t.id, "date": t.txn_date.isoformat(), "merchant": t.merchant,
            "amount": float(t.amount), "is_transfer": t.is_transfer,
            "institution_id": t.institution_id,
            "income_category_id": t.income_category_id,
            "expense_subcategory_id": t.expense_subcategory_id}


def _validate(s, user_id, f) -> None:
    """Normalise transfers and verify every referenced row belongs to this user."""
    if f["is_transfer"]:
        f["income_category_id"] = f["expense_subcategory_id"] = None
    elif f["income_category_id"] and f["expense_subcategory_id"]:
        raise ValueError("Choose either an income or an expense category, not both.")
    if f["institution_id"]:
        require_root(s, CashInstitution, f["institution_id"], user_id)
    if f["income_category_id"]:
        require_root(s, IncomeCategory, f["income_category_id"], user_id)
    if f["expense_subcategory_id"]:
        require_child(s, ExpenseSubcategory, "category_id", ExpenseCategory,
                      f["expense_subcategory_id"], user_id)


def get_transactions_page(user_id: str) -> dict:
    """Transactions plus the lookup lists the page's dropdowns need."""
    with SessionLocal.begin() as s:
        txns = s.scalars(select(Transaction).where(Transaction.user_id == user_id)
                         .order_by(Transaction.txn_date.desc(), Transaction.created_at.desc())).all()
        exp = roots(s, ExpenseCategory, user_id)
        subs = s.scalars(select(ExpenseSubcategory)
                         .where(ExpenseSubcategory.category_id.in_([c.id for c in exp]))
                         .order_by(ExpenseSubcategory.name)).all()
        return {
            "transactions": [_row(t) for t in txns],
            "banks":   [{"id": b.id, "name": b.name} for b in roots(s, CashInstitution, user_id)],
            "income":  [{"id": c.id, "name": c.name} for c in roots(s, IncomeCategory, user_id)],
            "expenses": [{"id": c.id, "name": c.name,
                          "subcategories": [{"id": sc.id, "name": sc.name}
                                            for sc in subs if sc.category_id == c.id]}
                         for c in exp],
        }


def create_transaction(user_id: str, f: dict) -> dict:
    with SessionLocal.begin() as s:
        _validate(s, user_id, f)
        t = Transaction(user_id=user_id, **f)
        s.add(t)
        s.flush()
        return _row(t)


def update_transaction(user_id: str, txn_id: str, f: dict) -> dict:
    with SessionLocal.begin() as s:
        t = s.scalar(select(Transaction).where(Transaction.id == txn_id, Transaction.user_id == user_id))
        if t is None:
            raise NotFound(txn_id)
        _validate(s, user_id, f)
        for k, v in f.items():
            setattr(t, k, v)
        return _row(t)


def delete_transaction(user_id: str, txn_id: str) -> None:
    delete_root(Transaction, user_id, txn_id)
