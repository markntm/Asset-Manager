"""Transactions → cashflow cells."""

import calendar
from datetime import date

from sqlalchemy import func, select
from database.base import upsert_cell
from database.models import ExpenseEntry, IncomeEntry, Transaction


def cell_keys(txn_date, is_transfer, income_category_id, expense_subcategory_id) -> set:
    """The cashflow cell(s) a transaction feeds. Transfers feed none."""
    if is_transfer:
        return set()
    mi, keys = txn_date.month - 1, set()
    if income_category_id:
        keys.add(("inc", income_category_id, txn_date.year, mi))
    if expense_subcategory_id:
        keys.add(("exp", expense_subcategory_id, txn_date.year, mi))
    return keys


def sync_cashflow(s, keys) -> None:
    """Recompute each affected cell from its transactions (no transactions → cell deleted)."""
    for kind, pid, year, mi in keys:
        first = date(year, mi + 1, 1)
        last = date(year, mi + 1, calendar.monthrange(year, mi + 1)[1])
        col = Transaction.income_category_id if kind == "inc" else Transaction.expense_subcategory_id
        total = s.scalar(select(func.sum(Transaction.amount)).where(
            col == pid, Transaction.is_transfer.is_(False), Transaction.txn_date.between(first, last)))
        if kind == "inc":
            upsert_cell(s, IncomeEntry, "category_id", pid, year, mi, total)
        else:
            upsert_cell(s, ExpenseEntry, "subcategory_id", pid, year, mi,
                        None if total is None else -total)
