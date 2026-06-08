"""
database.py — FinTrack SQLite data layer
Full implementation using Python's built-in sqlite3 module.
"""
from __future__ import annotations
import sqlite3
import uuid
from typing import Optional
from pathlib import Path

DB_PATH = Path(__file__).parent / "fintrack.db"


# ═══════════════════════════════════════════════════════════════════
#  CONNECTION HELPER
# ═══════════════════════════════════════════════════════════════════

def _conn() -> sqlite3.Connection:
    """Return a connection with foreign keys enabled and row_factory set."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _uid() -> str:
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════════
#  INIT — create all tables on first run
# ═══════════════════════════════════════════════════════════════════

def init_db() -> None:
    with _conn() as con:
        con.executescript("""
                          -- ── Cash Flow ──────────────────────────────────────────

                          CREATE TABLE IF NOT EXISTS cf_income_categories (
                                                                              id         TEXT PRIMARY KEY,
                                                                              name       TEXT NOT NULL,
                                                                              sort_order INTEGER NOT NULL DEFAULT 0
                          );

                          CREATE TABLE IF NOT EXISTS cf_income_values (
                                                                          category_id TEXT NOT NULL
                                                                          REFERENCES cf_income_categories(id) ON DELETE CASCADE,
                              year        INTEGER NOT NULL,
                              month_idx   INTEGER NOT NULL CHECK (month_idx BETWEEN 0 AND 11),
                              value       REAL    NOT NULL,
                              PRIMARY KEY (category_id, year, month_idx)
                              );

                          CREATE TABLE IF NOT EXISTS cf_expense_categories (
                                                                               id         TEXT PRIMARY KEY,
                                                                               name       TEXT NOT NULL,
                                                                               type       TEXT NOT NULL
                                                                               CHECK (type IN ('discretionary', 'fixed', 'one-time')),
                              sort_order INTEGER NOT NULL DEFAULT 0
                              );

                          CREATE TABLE IF NOT EXISTS cf_expense_values (
                                                                           category_id TEXT NOT NULL
                                                                           REFERENCES cf_expense_categories(id) ON DELETE CASCADE,
                              year        INTEGER NOT NULL,
                              month_idx   INTEGER NOT NULL CHECK (month_idx BETWEEN 0 AND 11),
                              value       REAL    NOT NULL,
                              PRIMARY KEY (category_id, year, month_idx)
                              );

                          -- ── Net Worth ───────────────────────────────────────────

                          CREATE TABLE IF NOT EXISTS nw_accounts (
                                                                     id         TEXT PRIMARY KEY,
                                                                     name       TEXT NOT NULL,
                                                                     group_id   TEXT NOT NULL
                                                                     CHECK (group_id IN ('savings', 'investments', 'assets')),
                              sort_order INTEGER NOT NULL DEFAULT 0
                              );

                          CREATE TABLE IF NOT EXISTS nw_values (
                                                                   account_id TEXT    NOT NULL
                                                                   REFERENCES nw_accounts(id) ON DELETE CASCADE,
                              year       INTEGER NOT NULL,
                              month_idx  INTEGER NOT NULL CHECK (month_idx BETWEEN 0 AND 11),
                              value      REAL    NOT NULL,
                              PRIMARY KEY (account_id, year, month_idx)
                              );
                          """)


# ═══════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════

def get_dashboard_summary() -> dict:
    from datetime import date
    today     = date.today()
    year      = today.year
    month_idx = today.month - 1          # 0-based

    with _conn() as con:

        # ── Net worth trend (all 12 months of current year) ──────
        nw_trend: list[Optional[float]] = [None] * 12

        rows = con.execute("""
                           SELECT month_idx, SUM(value) AS total
                           FROM   nw_values
                           WHERE  year = ?
                           GROUP  BY month_idx
                           ORDER  BY month_idx
                           """, (year,)).fetchall()

        for row in rows:
            nw_trend[row["month_idx"]] = row["total"]

        # Current and previous month net worth
        nw_current = nw_trend[month_idx] or 0.0
        nw_prev    = nw_trend[month_idx - 1] if month_idx > 0 else None
        mom_change = (nw_current - nw_prev) if nw_prev is not None else None
        mom_pct    = ((mom_change / nw_prev) * 100
                      if mom_change is not None and nw_prev else None)

        # ── Group totals (allocation) ─────────────────────────────
        alloc_rows = con.execute("""
                                 SELECT   a.group_id, SUM(v.value) AS total
                                 FROM     nw_values v
                                              JOIN     nw_accounts a ON a.id = v.account_id
                                 WHERE    v.year = ? AND v.month_idx = ?
                                 GROUP BY a.group_id
                                 """, (year, month_idx)).fetchall()

        allocation = {"savings": 0.0, "investments": 0.0, "assets": 0.0}
        for row in alloc_rows:
            allocation[row["group_id"]] = row["total"]

        total_cash        = allocation["savings"]
        total_investments = allocation["investments"]

        # ── Monthly cash flow (current month) ─────────────────────
        inc_row = con.execute("""
                              SELECT COALESCE(SUM(value), 0) AS total
                              FROM   cf_income_values
                              WHERE  year = ? AND month_idx = ?
                              """, (year, month_idx)).fetchone()

        exp_row = con.execute("""
                              SELECT COALESCE(SUM(value), 0) AS total
                              FROM   cf_expense_values
                              WHERE  year = ? AND month_idx = ?
                              """, (year, month_idx)).fetchone()

        monthly_income   = inc_row["total"]
        monthly_expenses = exp_row["total"]
        monthly_cashflow = monthly_income - monthly_expenses
        savings_rate     = ((monthly_cashflow / monthly_income * 100)
                            if monthly_income > 0 else 0.0)

        # ── Per-account snapshot ──────────────────────────────────
        acct_rows = con.execute("""
                                SELECT   a.id, a.name, a.group_id,
                                         COALESCE(v.value, 0)      AS balance,
                                         COALESCE(prev.value, 0)   AS prev_balance
                                FROM     nw_accounts a
                                             LEFT JOIN nw_values v
                                                       ON v.account_id = a.id
                                                           AND v.year       = ?
                                                           AND v.month_idx  = ?
                                             LEFT JOIN nw_values prev
                                                       ON prev.account_id = a.id
                                                           AND prev.year       = ?
                                                           AND prev.month_idx  = ?
                                ORDER BY a.group_id, a.sort_order
                                """, (year, month_idx, year, month_idx - 1)).fetchall()

        accounts = []
        for r in acct_rows:
            pct = (r["balance"] / nw_current * 100) if nw_current else 0.0
            accounts.append({
                "name":         r["name"],
                "institution":  r["name"],      # refine when institution field added
                "type":         r["group_id"],
                "balance":      r["balance"],
                "pct_of_total": round(pct, 2),
                "mom_change":   r["balance"] - r["prev_balance"],
            })

    return {
        "net_worth":          nw_current,
        "total_cash":         total_cash,
        "total_investments":  total_investments,
        "monthly_cashflow":   monthly_cashflow,
        "savings_rate":       round(savings_rate, 2),
        "nw_mom_change":      mom_change,
        "nw_mom_pct":         round(mom_pct, 2) if mom_pct is not None else None,
        "net_worth_trend":    nw_trend,
        "allocation":         allocation,
        "accounts":           accounts,
    }


# ═══════════════════════════════════════════════════════════════════
#  CASH FLOW
# ═══════════════════════════════════════════════════════════════════

def get_cashflow_year(year: int) -> dict:
    with _conn() as con:

        # Income categories
        inc_cats = con.execute("""
                               SELECT id, name FROM cf_income_categories ORDER BY sort_order, name
                               """).fetchall()

        # Income values for this year
        inc_vals = con.execute("""
                               SELECT category_id, month_idx, value
                               FROM   cf_income_values
                               WHERE  year = ?
                               """, (year,)).fetchall()

        inc_map: dict[str, dict] = {r["id"]: {} for r in inc_cats}
        for v in inc_vals:
            inc_map[v["category_id"]][str(v["month_idx"])] = v["value"]

        income = [
            {"id": r["id"], "name": r["name"], "values": inc_map[r["id"]]}
            for r in inc_cats
        ]

        # Expense categories
        exp_cats = con.execute("""
                               SELECT id, name, type FROM cf_expense_categories ORDER BY sort_order, name
                               """).fetchall()

        exp_vals = con.execute("""
                               SELECT category_id, month_idx, value
                               FROM   cf_expense_values
                               WHERE  year = ?
                               """, (year,)).fetchall()

        exp_map: dict[str, dict] = {r["id"]: {} for r in exp_cats}
        for v in exp_vals:
            exp_map[v["category_id"]][str(v["month_idx"])] = v["value"]

        expenses = [
            {
                "id":     r["id"],
                "name":   r["name"],
                "type":   r["type"],
                "values": exp_map[r["id"]],
            }
            for r in exp_cats
        ]

    return {"year": year, "income": income, "expenses": expenses}


def create_income_category(name: str) -> dict:
    new_id = _uid()
    with _conn() as con:
        order = con.execute(
            "SELECT COALESCE(MAX(sort_order)+1, 0) FROM cf_income_categories"
        ).fetchone()[0]
        con.execute(
            "INSERT INTO cf_income_categories (id, name, sort_order) VALUES (?,?,?)",
            (new_id, name, order),
        )
    return {"id": new_id, "name": name}


def update_income_category(category_id: str, name: str) -> dict | None:
    with _conn() as con:
        cur = con.execute(
            "UPDATE cf_income_categories SET name=? WHERE id=?", (name, category_id)
        )
        if cur.rowcount == 0:
            return None
    return {"id": category_id, "name": name}


def delete_income_category(category_id: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM cf_income_categories WHERE id=?", (category_id,)
        )
    return cur.rowcount > 0


def create_expense_category(name: str, type_: str) -> dict:
    new_id = _uid()
    with _conn() as con:
        order = con.execute(
            "SELECT COALESCE(MAX(sort_order)+1, 0) FROM cf_expense_categories"
        ).fetchone()[0]
        con.execute(
            "INSERT INTO cf_expense_categories (id, name, type, sort_order) VALUES (?,?,?,?)",
            (new_id, name, type_, order),
        )
    return {"id": new_id, "name": name, "type": type_}


def update_expense_category(
        category_id: str,
        name: Optional[str],
        type_: Optional[str],
) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT id, name, type FROM cf_expense_categories WHERE id=?",
            (category_id,)
        ).fetchone()
        if not row:
            return None
        new_name = name  if name  is not None else row["name"]
        new_type = type_ if type_ is not None else row["type"]
        con.execute(
            "UPDATE cf_expense_categories SET name=?, type=? WHERE id=?",
            (new_name, new_type, category_id),
        )
    return {"id": category_id, "name": new_name, "type": new_type}


def delete_expense_category(category_id: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM cf_expense_categories WHERE id=?", (category_id,)
        )
    return cur.rowcount > 0


def upsert_cashflow_cell(
        table:     str,
        row_id:    str,
        year:      int,
        month_idx: int,
        value:     Optional[float],
) -> None:
    tbl_values = (
        "cf_income_values"  if table == "income" else "cf_expense_values"
    )
    tbl_col = (
        "category_id"
    )
    with _conn() as con:
        if value is None:
            con.execute(
                f"DELETE FROM {tbl_values} WHERE category_id=? AND year=? AND month_idx=?",
                (row_id, year, month_idx),
            )
        else:
            con.execute(
                f"""INSERT INTO {tbl_values} (category_id, year, month_idx, value)
                    VALUES (?,?,?,?)
                    ON CONFLICT(category_id, year, month_idx)
                    DO UPDATE SET value=excluded.value""",
                (row_id, year, month_idx, value),
            )


# ═══════════════════════════════════════════════════════════════════
#  NET WORTH
# ═══════════════════════════════════════════════════════════════════

def get_accounts_structure() -> dict:
    with _conn() as con:
        rows = con.execute("""
                           SELECT id, name, group_id
                           FROM   nw_accounts
                           ORDER  BY group_id, sort_order, name
                           """).fetchall()

    structure: dict[str, list] = {"savings": [], "investments": [], "assets": []}
    for r in rows:
        structure[r["group_id"]].append({
            "id":       r["id"],
            "name":     r["name"],
            "group_id": r["group_id"],
        })
    return structure


def get_networth_year(year: int) -> dict:
    with _conn() as con:
        acct_rows = con.execute("""
                                SELECT id, name, group_id
                                FROM   nw_accounts
                                ORDER  BY group_id, sort_order, name
                                """).fetchall()

        val_rows = con.execute("""
                               SELECT account_id, month_idx, value
                               FROM   nw_values
                               WHERE  year = ?
                               """, (year,)).fetchall()

    val_map: dict[str, dict] = {r["id"]: {} for r in acct_rows}
    for v in val_rows:
        val_map[v["account_id"]][str(v["month_idx"])] = v["value"]

    structure: dict[str, list] = {"savings": [], "investments": [], "assets": []}
    rows_out  = []

    for r in acct_rows:
        acct = {"id": r["id"], "name": r["name"], "group_id": r["group_id"]}
        structure[r["group_id"]].append(acct)
        rows_out.append({
            "id":       r["id"],
            "name":     r["name"],
            "group_id": r["group_id"],
            "values":   val_map[r["id"]],
        })

    return {"year": year, "accounts": structure, "rows": rows_out}


def create_account(group_id: str, name: str) -> dict:
    new_id = _uid()
    with _conn() as con:
        order = con.execute(
            "SELECT COALESCE(MAX(sort_order)+1, 0) FROM nw_accounts WHERE group_id=?",
            (group_id,)
        ).fetchone()[0]
        con.execute(
            "INSERT INTO nw_accounts (id, name, group_id, sort_order) VALUES (?,?,?,?)",
            (new_id, name, group_id, order),
        )
    return {"id": new_id, "name": name, "group_id": group_id}


def update_account(account_id: str, name: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT group_id FROM nw_accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not row:
            return None
        con.execute(
            "UPDATE nw_accounts SET name=? WHERE id=?", (name, account_id)
        )
    return {"id": account_id, "name": name, "group_id": row["group_id"]}


def delete_account(account_id: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM nw_accounts WHERE id=?", (account_id,)
        )
    return cur.rowcount > 0


def upsert_networth_cell(
        item_id:   str,
        year:      int,
        month_idx: int,
        value:     Optional[float],
) -> None:
    with _conn() as con:
        if value is None:
            con.execute(
                "DELETE FROM nw_values WHERE account_id=? AND year=? AND month_idx=?",
                (item_id, year, month_idx),
            )
        else:
            con.execute(
                """INSERT INTO nw_values (account_id, year, month_idx, value)
                   VALUES (?,?,?,?)
                       ON CONFLICT(account_id, year, month_idx)
                   DO UPDATE SET value=excluded.value""",
                (item_id, year, month_idx, value),
            )






# ── Year load ───────────────────────────────────────────────────────────────
def get_cashflow_year(year: int) -> dict: ...
    # Returns CashFlowYearOut-shaped dict:
    # { "year": int, "income": [income_rows], "expenses": [expense_cats] }

# ── Income ──────────────────────────────────────────────────────────────────
def income_category_exists(category_id: str) -> bool: ...
def create_income_category(name: str) -> dict: ...          # {id, name}
def update_income_category(category_id: str, name: str) -> Optional[dict]: ...
def delete_income_category(category_id: str) -> bool: ...
def upsert_income_entry(
        category_id: str, year: int, month_idx: int, value: Optional[float]
) -> None: ...

# ── Expense categories ───────────────────────────────────────────────────────
def expense_category_exists(category_id: str) -> bool: ...
def create_expense_category(name: str) -> dict: ...         # {id, name, subcategories:[]}
def update_expense_category(category_id: str, name: str) -> Optional[dict]: ...
def delete_expense_category(category_id: str) -> bool: ...  # cascades to subcategories + values

# ── Expense subcategories ────────────────────────────────────────────────────
def expense_subcategory_exists(subcategory_id: str) -> bool: ...
def create_expense_subcategory(category_id: str, name: str) -> dict: ...  # {id, name, category_id}
def update_expense_subcategory(subcategory_id: str, name: str) -> Optional[dict]: ...
def delete_expense_subcategory(subcategory_id: str) -> bool: ...

# ── Cell saves ───────────────────────────────────────────────────────────────
def upsert_expense_entry(
        subcategory_id: str, year: int, month_idx: int, value: Optional[float]
) -> None: ...
def upsert_budget_entry(
        category_id: str, year: int, month_idx: int, value: Optional[float]
) -> None: ...