"""
database.py — FinTrack SQLite data layer (stub functions)

Every function maps directly to one or more SQL queries.
The full implementation is in the next step (table design + backend).
Type hints here define the exact contract main.py depends on.
"""
from __future__ import annotations
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
#  INIT
# ═══════════════════════════════════════════════════════════════════

def init_db() -> None:
    """
    Open (or create) fintrack.db and run CREATE TABLE IF NOT EXISTS
    for every table. Called once at application startup.
    """
    ...


# ═══════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════

def get_dashboard_summary() -> dict:
    """
    Cross-table aggregation:
      - Net worth from latest filled month in nw_values
      - Monthly cash flow from cf_income_values + cf_expense_values (current month)
      - Savings rate = (income - expenses) / income * 100
      - 12-month net worth trend
      - Allocation by group
      - Per-account snapshot with MoM change
    Returns a DashboardSummaryOut-shaped dict.
    """
    ...


# ═══════════════════════════════════════════════════════════════════
#  CASH FLOW
# ═══════════════════════════════════════════════════════════════════

def get_cashflow_year(year: int) -> dict:
    """
    SELECT all income categories + their values for `year`.
    SELECT all expense categories + their values for `year`.
    Returns a CashFlowYearOut-shaped dict.
    """
    ...

def create_income_category(name: str) -> dict:
    """INSERT INTO cf_income_categories; return the new row as dict."""
    ...

def update_income_category(category_id: str, name: str) -> dict | None:
    """UPDATE cf_income_categories SET name=? WHERE id=?. Returns None if missing."""
    ...

def delete_income_category(category_id: str) -> bool:
    """
    DELETE FROM cf_income_categories WHERE id=?.
    CASCADE deletes all rows in cf_income_values for this category.
    Returns False if the row didn't exist.
    """
    ...

def create_expense_category(name: str, type_: str) -> dict:
    """INSERT INTO cf_expense_categories; return the new row as dict."""
    ...

def update_expense_category(
    category_id: str,
    name: Optional[str],
    type_: Optional[str],
) -> dict | None:
    """
    UPDATE cf_expense_categories with whichever fields are non-None.
    Returns None if not found.
    """
    ...

def delete_expense_category(category_id: str) -> bool:
    """
    DELETE FROM cf_expense_categories WHERE id=?.
    CASCADE deletes all rows in cf_expense_values.
    Returns False if the row didn't exist.
    """
    ...

def upsert_cashflow_cell(
    table:     str,            # 'income' | 'expense'
    row_id:    str,            # category UUID
    year:      int,
    month_idx: int,            # 0–11
    value:     Optional[float],  # None → DELETE the cell row
) -> None:
    """
    INSERT OR REPLACE into cf_income_values or cf_expense_values.
    If value is None, DELETE the row instead (keeps the table clean).
    """
    ...


# ═══════════════════════════════════════════════════════════════════
#  NET WORTH
# ═══════════════════════════════════════════════════════════════════

def get_accounts_structure() -> dict:
    """
    SELECT all rows from nw_accounts ORDER BY group_id, sort_order.
    Returns an AccountsStructureOut-shaped dict with three lists.
    """
    ...

def get_networth_year(year: int) -> dict:
    """
    SELECT account structure + all nw_values rows WHERE year=?.
    Returns a NetWorthYearOut-shaped dict.
    """
    ...

def create_account(group_id: str, name: str) -> dict:
    """INSERT INTO nw_accounts; return the new row as dict."""
    ...

def update_account(account_id: str, name: str) -> dict | None:
    """UPDATE nw_accounts SET name=? WHERE id=?. Returns None if not found."""
    ...

def delete_account(account_id: str) -> bool:
    """
    DELETE FROM nw_accounts WHERE id=?.
    CASCADE deletes all rows in nw_values for this account across all years.
    Returns False if not found.
    """
    ...

def upsert_networth_cell(
    item_id:   str,
    year:      int,
    month_idx: int,            # 0–11
    value:     Optional[float],  # None → DELETE the cell row
) -> None:
    """
    INSERT OR REPLACE into nw_values.
    If value is None, DELETE the row instead.
    """
    ...