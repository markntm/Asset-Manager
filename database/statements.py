"""Statement import: lookups, duplicate detection, category memory, commit."""

import hashlib
import uuid
from collections import Counter
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from database.base import SessionLocal, require_child, require_root, roots, upsert_cell
from database.models import (CashAccount, CashEntry, CashInstitution, ExpenseCategory,
                             ExpenseSubcategory, IncomeCategory, StatementImport, Transaction)
from database.sync import cell_keys, sync_cashflow
from calculations.statements import checksum, merchant_key


def get_lookups(user_id: str) -> dict:
    with SessionLocal.begin() as s:
        banks = roots(s, CashInstitution, user_id)
        accts = s.scalars(select(CashAccount)
                          .where(CashAccount.institution_id.in_([b.id for b in banks]))
                          .order_by(CashAccount.name)).all()
        exp = roots(s, ExpenseCategory, user_id)
        subs = s.scalars(select(ExpenseSubcategory)
                         .where(ExpenseSubcategory.category_id.in_([c.id for c in exp]))
                         .order_by(ExpenseSubcategory.name)).all()
        return {
            "banks": [{"id": b.id, "name": b.name,
                       "accounts": [{"id": a.id, "name": a.name} for a in accts if a.institution_id == b.id]}
                      for b in banks],
            "income": [{"id": c.id, "name": c.name} for c in roots(s, IncomeCategory, user_id)],
            "expenses": [{"id": c.id, "name": c.name,
                          "subcategories": [{"id": sc.id, "name": sc.name} for sc in subs if sc.category_id == c.id]}
                         for c in exp],
        }


# ── Duplicates ────────────────────────────────────────────────────────────────
# A row is a duplicate when the same bank already holds a transaction with the same date and amount.
# Counting (not a simple "exists") keeps two genuine identical purchases on one day, but flags a
# re-uploaded or overlapping statement.  Works against manual rows and earlier imports alike.

def _dupes(s, user_id, bank_id, items) -> list[bool]:
    valid = [(d, round(a, 2)) for d, a in items if d is not None and a is not None]
    if not valid:
        return [False] * len(items)
    q = (select(Transaction.txn_date, Transaction.amount, func.count())
         .where(Transaction.user_id == user_id,
                Transaction.txn_date.between(min(d for d, _ in valid), max(d for d, _ in valid)),
                Transaction.institution_id == bank_id if bank_id else Transaction.institution_id.is_(None))
         .group_by(Transaction.txn_date, Transaction.amount))
    existing = {(d, round(float(a), 2)): n for d, a, n in s.execute(q)}
    seen, out = Counter(), []
    for d, a in items:
        if d is None or a is None:
            out.append(False)
            continue
        k = (d, round(a, 2))
        out.append(seen[k] < existing.get(k, 0))
        seen[k] += 1
    return out


def check_duplicates(user_id, bank_id, items) -> list[bool]:
    with SessionLocal.begin() as s:
        return _dupes(s, user_id, bank_id, items)


def _category_memory(s, user_id) -> dict:
    """merchant key → 'inc:<id>' | 'exp:<id>' from the user's own history (newest wins)."""
    q = (select(Transaction.merchant, Transaction.income_category_id, Transaction.expense_subcategory_id)
         .where(Transaction.user_id == user_id, Transaction.is_transfer.is_(False),
                Transaction.income_category_id.is_not(None) | Transaction.expense_subcategory_id.is_not(None))
         .order_by(Transaction.txn_date.desc()).limit(5000))
    out = {}
    for m, inc, exp in s.execute(q):
        out.setdefault(merchant_key(m), f"inc:{inc}" if inc else f"exp:{exp}")
    return out


def enrich(user_id: str, parsed: dict, lookups: dict) -> dict:
    """Add duplicate flags + remembered categories to a parse result."""
    with SessionLocal.begin() as s:
        rows = parsed["rows"]
        dup = _dupes(s, user_id, parsed["meta"]["bank_id"],
                     [(date.fromisoformat(r["date"]) if r["date"] else None, r["amount"]) for r in rows])
        known = _category_memory(s, user_id)
        for r, d in zip(rows, dup):
            r["duplicate"] = d
            r["category"] = None if r["is_transfer"] else known.get(merchant_key(r["merchant"]))
    parsed["lookups"] = lookups
    return parsed


# ── Commit ────────────────────────────────────────────────────────────────────

def _check_owned(s, user_id, inc_ids, exp_ids) -> None:
    if inc_ids:
        owned = set(s.scalars(select(IncomeCategory.id).where(IncomeCategory.user_id == user_id,
                                                              IncomeCategory.id.in_(inc_ids))))
        if owned != inc_ids:
            raise ValueError("Unknown income category.")
    if exp_ids:
        owned = set(s.scalars(select(ExpenseSubcategory.id)
                              .join(ExpenseCategory, ExpenseSubcategory.category_id == ExpenseCategory.id)
                              .where(ExpenseCategory.user_id == user_id, ExpenseSubcategory.id.in_(exp_ids))))
        if owned != exp_ids:
            raise ValueError("Unknown expense category.")


def commit_statement(user_id: str, meta: dict, rows: list[dict]) -> dict:
    with SessionLocal.begin() as s:
        bank = meta["bank_id"]
        if bank:
            require_root(s, CashInstitution, bank, user_id)
        live = [r for r in rows if not r["is_transfer"] and r["category"]]
        _check_owned(s, user_id,
                     {r["category"][4:] for r in live if r["category"].startswith("inc:")},
                     {r["category"][4:] for r in live if r["category"].startswith("exp:")})

        dup = _dupes(s, user_id, bank, [(r["date"], r["amount"]) for r in rows])
        seen, vals, keys = Counter(), [], set()
        for r, is_dup in zip(rows, dup):
            k = (r["date"], round(r["amount"], 2))
            occ = seen[k]
            seen[k] += 1
            if is_dup:
                continue
            cat = None if r["is_transfer"] else r["category"]
            inc = cat[4:] if cat and cat.startswith("inc:") else None
            exp = cat[4:] if cat and cat.startswith("exp:") else None
            h = hashlib.sha256(f"{bank or ''}|{r['date'].isoformat()}|{r['amount']:.2f}|{occ}".encode()).hexdigest()
            vals.append({"id": str(uuid.uuid4()), "user_id": user_id, "txn_date": r["date"],
                         "merchant": r["merchant"], "amount": r["amount"], "is_transfer": r["is_transfer"],
                         "institution_id": bank, "income_category_id": inc, "expense_subcategory_id": exp,
                         "import_hash": h})
            keys |= cell_keys(r["date"], r["is_transfer"], inc, exp)

        inserted = 0
        if vals:   # the unique (user_id, import_hash) index is a second line of defence against races
            stmt = insert(Transaction).values(vals).on_conflict_do_nothing(index_elements=["user_id", "import_hash"])
            inserted = len(s.execute(stmt.returning(Transaction.id)).all())
            sync_cashflow(s, keys)

        cs = checksum(meta["statement_type"], meta["opening_balance"], meta["closing_balance"],
                      [r["amount"] for r in rows])

        nw = False
        pe = meta["period_end"]
        if (meta["update_networth"] and meta["account_id"] and pe and meta["closing_balance"] is not None
                and meta["statement_type"] != "credit"):
            require_child(s, CashAccount, "institution_id", CashInstitution, meta["account_id"], user_id)
            upsert_cell(s, CashEntry, "account_id", meta["account_id"], pe.year, pe.month - 1, meta["closing_balance"])
            nw = True

        rec = StatementImport(
            user_id=user_id, institution_id=bank, statement_type=meta["statement_type"],
            period_start=meta["period_start"], period_end=pe,
            opening_balance=meta["opening_balance"], closing_balance=meta["closing_balance"],
            txn_total=cs["txn_total"], diff=cs["diff"], checksum_status=cs["status"],
            rows_total=len(rows), rows_imported=inserted)
        s.add(rec)
        s.flush()
        return {"import_id": rec.id, "imported": inserted, "skipped_duplicates": len(rows) - inserted,
                "checksum": cs, "networth_updated": nw}


def list_imports(user_id: str) -> list[dict]:
    f = lambda v: float(v) if v is not None else None
    with SessionLocal.begin() as s:
        rows = s.scalars(select(StatementImport).where(StatementImport.user_id == user_id)
                         .order_by(StatementImport.created_at.desc()).limit(50)).all()
        return [{"id": r.id, "created_at": r.created_at.isoformat(), "institution_id": r.institution_id,
                 "statement_type": r.statement_type,
                 "period_start": r.period_start.isoformat() if r.period_start else None,
                 "period_end": r.period_end.isoformat() if r.period_end else None,
                 "opening_balance": f(r.opening_balance), "closing_balance": f(r.closing_balance),
                 "txn_total": f(r.txn_total), "diff": f(r.diff), "checksum_status": r.checksum_status,
                 "rows_total": r.rows_total, "rows_imported": r.rows_imported} for r in rows]
