"""ORM Classes"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

MONEY = Numeric(14, 2)


def _fk(target: str):
    return mapped_column(String(36), ForeignKey(f"{target}.id", ondelete="CASCADE"), index=True)


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class RootMixin(IdMixin):
    """Top-level rows: the only tables that point at a user."""
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @declared_attr
    def user_id(cls) -> Mapped[str]:
        return mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)


class EntryMixin(IdMixin):
    """One monthly value cell."""
    year: Mapped[int] = mapped_column()
    month_idx: Mapped[int] = mapped_column()
    value: Mapped[Decimal] = mapped_column(MONEY)


class User(IdMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    failed_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ── Cash flow ──
class IncomeCategory(RootMixin, Base):
    __tablename__ = "cf_income_categories"

class IncomeEntry(EntryMixin, Base):
    __tablename__ = "cf_income_entries"
    category_id: Mapped[str] = _fk("cf_income_categories")
    __table_args__ = (UniqueConstraint("category_id", "year", "month_idx"),)

class ExpenseCategory(RootMixin, Base):
    __tablename__ = "cf_expense_categories"

class ExpenseSubcategory(IdMixin, Base):
    __tablename__ = "cf_expense_subcategories"
    category_id: Mapped[str] = _fk("cf_expense_categories")
    name: Mapped[str] = mapped_column(String(200))

class ExpenseEntry(EntryMixin, Base):
    __tablename__ = "cf_expense_entries"
    subcategory_id: Mapped[str] = _fk("cf_expense_subcategories")
    __table_args__ = (UniqueConstraint("subcategory_id", "year", "month_idx"),)

class BudgetEntry(EntryMixin, Base):
    __tablename__ = "cf_budget_entries"
    category_id: Mapped[str] = _fk("cf_expense_categories")
    __table_args__ = (UniqueConstraint("category_id", "year", "month_idx"),)

class BudgetTarget(Base):
    __tablename__ = "budget_targets"
    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cf_expense_categories.id", ondelete="CASCADE"), primary_key=True)
    monthly_budget: Mapped[Optional[Decimal]] = mapped_column(MONEY)


# ── Net worth ──
class CashInstitution(RootMixin, Base):
    __tablename__ = "nw_cash_institutions"

class CashAccount(IdMixin, Base):
    __tablename__ = "nw_cash_accounts"
    institution_id: Mapped[str] = _fk("nw_cash_institutions")
    name: Mapped[str] = mapped_column(String(200))

class CashEntry(EntryMixin, Base):
    __tablename__ = "nw_cash_entries"
    account_id: Mapped[str] = _fk("nw_cash_accounts")
    __table_args__ = (UniqueConstraint("account_id", "year", "month_idx"),)

class Brokerage(RootMixin, Base):
    __tablename__ = "nw_inv_brokerages"

class Holding(IdMixin, Base):
    __tablename__ = "nw_inv_holdings"
    brokerage_id: Mapped[str] = _fk("nw_inv_brokerages")
    ticker: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)

class InvEntry(EntryMixin, Base):
    __tablename__ = "nw_inv_entries"
    holding_id: Mapped[str] = _fk("nw_inv_holdings")
    __table_args__ = (UniqueConstraint("holding_id", "year", "month_idx"),)

class AssetCategory(RootMixin, Base):
    __tablename__ = "nw_asset_categories"

class AssetItem(IdMixin, Base):
    __tablename__ = "nw_asset_items"
    category_id: Mapped[str] = _fk("nw_asset_categories")
    name: Mapped[str] = mapped_column(String(200))

class AssetEntry(EntryMixin, Base):
    __tablename__ = "nw_asset_entries"
    item_id: Mapped[str] = _fk("nw_asset_items")
    __table_args__ = (UniqueConstraint("item_id", "year", "month_idx"),)


# ── Transactions ──
class Transaction(IdMixin, Base):
    __tablename__ = "transactions"
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    merchant: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(MONEY)              # negative = outflow, positive = inflow
    is_transfer: Mapped[bool] = mapped_column(default=False, server_default="false")
    institution_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("nw_cash_institutions.id", ondelete="SET NULL"), index=True)
    income_category_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("cf_income_categories.id", ondelete="SET NULL"))
    expense_subcategory_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("cf_expense_subcategories.id", ondelete="SET NULL"))
    import_hash: Mapped[Optional[str]] = mapped_column(String(64))   # dedupe key for the future statement reader
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("user_id", "import_hash"),)

class StatementImport(IdMixin, Base):
    """Totals + checksum of an import. The statement itself is never stored."""
    __tablename__ = "statement_imports"
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    institution_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("nw_cash_institutions.id", ondelete="SET NULL"))
    statement_type: Mapped[str] = mapped_column(String(20))
    period_start: Mapped[Optional[date]] = mapped_column(Date)
    period_end: Mapped[Optional[date]] = mapped_column(Date)
    opening_balance: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    closing_balance: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    txn_total: Mapped[Decimal] = mapped_column(MONEY)
    diff: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    checksum_status: Mapped[str] = mapped_column(String(12))      # ok | mismatch | unverified
    rows_total: Mapped[int] = mapped_column()
    rows_imported: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
