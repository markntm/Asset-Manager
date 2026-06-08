"""
database.py  —  SQLite persistence layer for FinTrack.
────────────────────────────────────────────────────────
All I/O is synchronous (stdlib sqlite3).  FastAPI runs sync handlers in a
thread-pool executor, so the event loop is never blocked.

Each public function opens its own connection, executes inside a single
transaction, then closes.  This is correct and safe for a single-user app.

Return shapes are designed to feed directly into the calculation functions
in calculations/cashflow.py and calculations/networth.py without
any further transformation.
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "fintrack.db"


# ═════════════════════════════════════════════════════════════════════════════
#  CONNECTION
# ═════════════════════════════════════════════════════════════════════════════

@contextmanager
def _db():
    """
    Yield an sqlite3 connection with Row factory enabled.
    Auto-commits on clean exit; rolls back on any exception.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _uid() -> str:
    return str(uuid.uuid4())


def _to_values(rows) -> dict:
    """Convert [(month_idx, value), …] rows → {"0": float, …}."""
    return {str(r["month_idx"]): float(r["value"]) for r in rows}


# ═════════════════════════════════════════════════════════════════════════════
#  SCHEMA
# ═════════════════════════════════════════════════════════════════════════════

_SCHEMA = """
          -- Cash Flow
          CREATE TABLE IF NOT EXISTS cf_income_categories (
                                                              id   TEXT PRIMARY KEY,
                                                              name TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS cf_income_entries (
                                                           id          TEXT PRIMARY KEY,
                                                           category_id TEXT    NOT NULL REFERENCES cf_income_categories(id) ON DELETE CASCADE,
              year        INTEGER NOT NULL,
              month_idx   INTEGER NOT NULL,
              value       REAL    NOT NULL,
              UNIQUE(category_id, year, month_idx)
              );
          CREATE TABLE IF NOT EXISTS cf_expense_categories (
                                                               id   TEXT PRIMARY KEY,
                                                               name TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS cf_expense_subcategories (
                                                                  id          TEXT PRIMARY KEY,
                                                                  category_id TEXT NOT NULL REFERENCES cf_expense_categories(id) ON DELETE CASCADE,
              name        TEXT NOT NULL
              );
          CREATE TABLE IF NOT EXISTS cf_expense_entries (
                                                            id             TEXT PRIMARY KEY,
                                                            subcategory_id TEXT    NOT NULL REFERENCES cf_expense_subcategories(id) ON DELETE CASCADE,
              year           INTEGER NOT NULL,
              month_idx      INTEGER NOT NULL,
              value          REAL    NOT NULL,
              UNIQUE(subcategory_id, year, month_idx)
              );
          CREATE TABLE IF NOT EXISTS cf_budget_entries (
                                                           id          TEXT PRIMARY KEY,
                                                           category_id TEXT    NOT NULL REFERENCES cf_expense_categories(id) ON DELETE CASCADE,
              year        INTEGER NOT NULL,
              month_idx   INTEGER NOT NULL,
              value       REAL    NOT NULL,
              UNIQUE(category_id, year, month_idx)
              );

-- Net Worth
          CREATE TABLE IF NOT EXISTS nw_cash_institutions (
                                                              id   TEXT PRIMARY KEY,
                                                              name TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS nw_cash_accounts (
                                                          id             TEXT PRIMARY KEY,
                                                          institution_id TEXT NOT NULL REFERENCES nw_cash_institutions(id) ON DELETE CASCADE,
              name           TEXT NOT NULL
              );
          CREATE TABLE IF NOT EXISTS nw_cash_entries (
                                                         id         TEXT PRIMARY KEY,
                                                         account_id TEXT    NOT NULL REFERENCES nw_cash_accounts(id) ON DELETE CASCADE,
              year       INTEGER NOT NULL,
              month_idx  INTEGER NOT NULL,
              value      REAL    NOT NULL,
              UNIQUE(account_id, year, month_idx)
              );
          CREATE TABLE IF NOT EXISTS nw_inv_brokerages (
                                                           id   TEXT PRIMARY KEY,
                                                           name TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS nw_inv_holdings (
                                                         id           TEXT PRIMARY KEY,
                                                         brokerage_id TEXT NOT NULL REFERENCES nw_inv_brokerages(id) ON DELETE CASCADE,
              ticker       TEXT NOT NULL,
              quantity     REAL NOT NULL DEFAULT 0
              );
          CREATE TABLE IF NOT EXISTS nw_inv_entries (
                                                        id         TEXT PRIMARY KEY,
                                                        holding_id TEXT    NOT NULL REFERENCES nw_inv_holdings(id) ON DELETE CASCADE,
              year       INTEGER NOT NULL,
              month_idx  INTEGER NOT NULL,
              value      REAL    NOT NULL,
              UNIQUE(holding_id, year, month_idx)
              );
          CREATE TABLE IF NOT EXISTS nw_asset_categories (
                                                             id   TEXT PRIMARY KEY,
                                                             name TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS nw_asset_items (
                                                        id          TEXT PRIMARY KEY,
                                                        category_id TEXT NOT NULL REFERENCES nw_asset_categories(id) ON DELETE CASCADE,
              name        TEXT NOT NULL
              );
          CREATE TABLE IF NOT EXISTS nw_asset_entries (
                                                          id        TEXT PRIMARY KEY,
                                                          item_id   TEXT    NOT NULL REFERENCES nw_asset_items(id) ON DELETE CASCADE,
              year      INTEGER NOT NULL,
              month_idx INTEGER NOT NULL,
              value     REAL    NOT NULL,
              UNIQUE(item_id, year, month_idx)
              );

-- Budget planning targets (single monthly figure per expense category)
          CREATE TABLE IF NOT EXISTS budget_targets (
                                                        category_id    TEXT PRIMARY KEY REFERENCES cf_expense_categories(id) ON DELETE CASCADE,
              monthly_budget REAL
              ); \
          """


def init_db() -> None:
    """Create all tables.  Safe to call on every startup (IF NOT EXISTS guards)."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)   # executescript issues an implicit COMMIT — fine for DDL
    conn.close()


# ═════════════════════════════════════════════════════════════════════════════
#  CASH FLOW — DATA LOAD
# ═════════════════════════════════════════════════════════════════════════════

def get_cashflow_data(year: int) -> dict:
    """
    Return all income rows and expense categories for one year.

    Shape matches calculations/cashflow.py expectations and the frontend
    STATE object (values dict keyed by string month index).
    """
    with _db() as conn:
        # ── Income ────────────────────────────────────────────────────
        income_rows: list[dict] = []
        for cat in conn.execute(
                "SELECT id, name FROM cf_income_categories"
        ).fetchall():
            entries = conn.execute(
                "SELECT month_idx, value FROM cf_income_entries "
                "WHERE category_id = ? AND year = ?",
                (cat["id"], year),
            ).fetchall()
            income_rows.append({
                "id":     cat["id"],
                "name":   cat["name"],
                "values": _to_values(entries),
            })

        # ── Expenses ──────────────────────────────────────────────────
        expense_cats: list[dict] = []
        for cat in conn.execute(
                "SELECT id, name FROM cf_expense_categories"
        ).fetchall():
            bud_entries = conn.execute(
                "SELECT month_idx, value FROM cf_budget_entries "
                "WHERE category_id = ? AND year = ?",
                (cat["id"], year),
            ).fetchall()
            subcats: list[dict] = []
            for sc in conn.execute(
                    "SELECT id, name FROM cf_expense_subcategories WHERE category_id = ?",
                    (cat["id"],),
            ).fetchall():
                sc_entries = conn.execute(
                    "SELECT month_idx, value FROM cf_expense_entries "
                    "WHERE subcategory_id = ? AND year = ?",
                    (sc["id"], year),
                ).fetchall()
                subcats.append({
                    "id":     sc["id"],
                    "name":   sc["name"],
                    "values": _to_values(sc_entries),
                })
            expense_cats.append({
                "id":            cat["id"],
                "name":          cat["name"],
                "budget":        _to_values(bud_entries),
                "subcategories": subcats,
            })

        return {"income": income_rows, "expenses": expense_cats}


# ═════════════════════════════════════════════════════════════════════════════
#  CASH FLOW — CRUD
# ═════════════════════════════════════════════════════════════════════════════

def add_income_category(name: str) -> dict:
    new_id = _uid()
    with _db() as conn:
        conn.execute(
            "INSERT INTO cf_income_categories (id, name) VALUES (?, ?)", (new_id, name)
        )
    return {"id": new_id, "name": name}


def delete_income_category(category_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM cf_income_categories WHERE id = ?", (category_id,))


def add_expense_category(name: str) -> dict:
    new_id = _uid()
    with _db() as conn:
        conn.execute(
            "INSERT INTO cf_expense_categories (id, name) VALUES (?, ?)", (new_id, name)
        )
    return {"id": new_id, "name": name}


def delete_expense_category(category_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM cf_expense_categories WHERE id = ?", (category_id,))


def add_expense_subcategory(category_id: str, name: str) -> dict:
    new_id = _uid()
    with _db() as conn:
        conn.execute(
            "INSERT INTO cf_expense_subcategories (id, category_id, name) VALUES (?, ?, ?)",
            (new_id, category_id, name),
        )
    return {"id": new_id, "name": name}


def delete_expense_subcategory(subcategory_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM cf_expense_subcategories WHERE id = ?", (subcategory_id,))


# ═════════════════════════════════════════════════════════════════════════════
#  CASH FLOW — UPSERTS
# ═════════════════════════════════════════════════════════════════════════════

def upsert_income_entry(
        category_id: str, year: int, month_idx: int, value: Optional[float]
) -> None:
    with _db() as conn:
        if value is None:
            conn.execute(
                "DELETE FROM cf_income_entries "
                "WHERE category_id = ? AND year = ? AND month_idx = ?",
                (category_id, year, month_idx),
            )
        else:
            conn.execute(
                "INSERT INTO cf_income_entries (id, category_id, year, month_idx, value) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(category_id, year, month_idx) DO UPDATE SET value = excluded.value",
                (_uid(), category_id, year, month_idx, value),
            )


def upsert_expense_entry(
        subcategory_id: str, year: int, month_idx: int, value: Optional[float]
) -> None:
    with _db() as conn:
        if value is None:
            conn.execute(
                "DELETE FROM cf_expense_entries "
                "WHERE subcategory_id = ? AND year = ? AND month_idx = ?",
                (subcategory_id, year, month_idx),
            )
        else:
            conn.execute(
                "INSERT INTO cf_expense_entries (id, subcategory_id, year, month_idx, value) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(subcategory_id, year, month_idx) DO UPDATE SET value = excluded.value",
                (_uid(), subcategory_id, year, month_idx, value),
            )


def upsert_budget_entry(
        category_id: str, year: int, month_idx: int, value: Optional[float]
) -> None:
    with _db() as conn:
        if value is None:
            conn.execute(
                "DELETE FROM cf_budget_entries "
                "WHERE category_id = ? AND year = ? AND month_idx = ?",
                (category_id, year, month_idx),
            )
        else:
            conn.execute(
                "INSERT INTO cf_budget_entries (id, category_id, year, month_idx, value) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(category_id, year, month_idx) DO UPDATE SET value = excluded.value",
                (_uid(), category_id, year, month_idx, value),
            )


# ═════════════════════════════════════════════════════════════════════════════
#  NET WORTH — DATA LOAD
# ═════════════════════════════════════════════════════════════════════════════

def get_networth_data(year: int) -> dict:
    """
    Return cash / investments / assets for one year.

    Shape matches calculations/networth.py expectations and the frontend
    STATE object.
    """
    with _db() as conn:
        # ── Cash ──────────────────────────────────────────────────────
        cash_list: list[dict] = []
        for inst in conn.execute(
                "SELECT id, name FROM nw_cash_institutions"
        ).fetchall():
            accounts: list[dict] = []
            for acc in conn.execute(
                    "SELECT id, name FROM nw_cash_accounts WHERE institution_id = ?",
                    (inst["id"],),
            ).fetchall():
                entries = conn.execute(
                    "SELECT month_idx, value FROM nw_cash_entries "
                    "WHERE account_id = ? AND year = ?",
                    (acc["id"], year),
                ).fetchall()
                accounts.append({
                    "id":     acc["id"],
                    "name":   acc["name"],
                    "values": _to_values(entries),
                })
            cash_list.append({
                "id":       inst["id"],
                "name":     inst["name"],
                "accounts": accounts,
            })

        # ── Investments ───────────────────────────────────────────────
        inv_list: list[dict] = []
        for brk in conn.execute(
                "SELECT id, name FROM nw_inv_brokerages"
        ).fetchall():
            holdings: list[dict] = []
            for h in conn.execute(
                    "SELECT id, ticker, quantity FROM nw_inv_holdings WHERE brokerage_id = ?",
                    (brk["id"],),
            ).fetchall():
                entries = conn.execute(
                    "SELECT month_idx, value FROM nw_inv_entries "
                    "WHERE holding_id = ? AND year = ?",
                    (h["id"], year),
                ).fetchall()
                holdings.append({
                    "id":       h["id"],
                    "ticker":   h["ticker"],
                    "quantity": float(h["quantity"]),
                    "values":   _to_values(entries),
                })
            inv_list.append({
                "id":       brk["id"],
                "name":     brk["name"],
                "holdings": holdings,
            })

        # ── Assets ────────────────────────────────────────────────────
        ast_list: list[dict] = []
        for cat in conn.execute(
                "SELECT id, name FROM nw_asset_categories"
        ).fetchall():
            items: list[dict] = []
            for item in conn.execute(
                    "SELECT id, name FROM nw_asset_items WHERE category_id = ?",
                    (cat["id"],),
            ).fetchall():
                entries = conn.execute(
                    "SELECT month_idx, value FROM nw_asset_entries "
                    "WHERE item_id = ? AND year = ?",
                    (item["id"], year),
                ).fetchall()
                items.append({
                    "id":     item["id"],
                    "name":   item["name"],
                    "values": _to_values(entries),
                })
            ast_list.append({
                "id":    cat["id"],
                "name":  cat["name"],
                "items": items,
            })

        return {"cash": cash_list, "investments": inv_list, "assets": ast_list}


# ═════════════════════════════════════════════════════════════════════════════
#  NET WORTH — CRUD
# ═════════════════════════════════════════════════════════════════════════════

def add_cash_institution(name: str) -> dict:
    new_id = _uid()
    with _db() as conn:
        conn.execute(
            "INSERT INTO nw_cash_institutions (id, name) VALUES (?, ?)", (new_id, name)
        )
    return {"id": new_id, "name": name}


def add_cash_account(institution_id: str, name: str) -> dict:
    new_id = _uid()
    with _db() as conn:
        conn.execute(
            "INSERT INTO nw_cash_accounts (id, institution_id, name) VALUES (?, ?, ?)",
            (new_id, institution_id, name),
        )
    return {"id": new_id, "name": name}


def delete_cash_institution(institution_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM nw_cash_institutions WHERE id = ?", (institution_id,))


def delete_cash_account(account_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM nw_cash_accounts WHERE id = ?", (account_id,))


def add_brokerage(name: str) -> dict:
    new_id = _uid()
    with _db() as conn:
        conn.execute(
            "INSERT INTO nw_inv_brokerages (id, name) VALUES (?, ?)", (new_id, name)
        )
    return {"id": new_id, "name": name}


def add_holding(brokerage_id: str, ticker: str, quantity: float) -> dict:
    new_id = _uid()
    with _db() as conn:
        conn.execute(
            "INSERT INTO nw_inv_holdings (id, brokerage_id, ticker, quantity) "
            "VALUES (?, ?, ?, ?)",
            (new_id, brokerage_id, ticker, quantity),
        )
    return {"id": new_id, "ticker": ticker, "quantity": quantity}


def update_holding_quantity(holding_id: str, quantity: float) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE nw_inv_holdings SET quantity = ? WHERE id = ?", (quantity, holding_id)
        )


def delete_brokerage(brokerage_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM nw_inv_brokerages WHERE id = ?", (brokerage_id,))


def delete_holding(holding_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM nw_inv_holdings WHERE id = ?", (holding_id,))


def add_asset_category(name: str) -> dict:
    new_id = _uid()
    with _db() as conn:
        conn.execute(
            "INSERT INTO nw_asset_categories (id, name) VALUES (?, ?)", (new_id, name)
        )
    return {"id": new_id, "name": name}


def add_asset_item(category_id: str, name: str) -> dict:
    new_id = _uid()
    with _db() as conn:
        conn.execute(
            "INSERT INTO nw_asset_items (id, category_id, name) VALUES (?, ?, ?)",
            (new_id, category_id, name),
        )
    return {"id": new_id, "name": name}


def delete_asset_category(category_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM nw_asset_categories WHERE id = ?", (category_id,))


def delete_asset_item(item_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM nw_asset_items WHERE id = ?", (item_id,))


# ═════════════════════════════════════════════════════════════════════════════
#  NET WORTH — CELL UPSERT
# ═════════════════════════════════════════════════════════════════════════════

def _resolve_item_type(conn, item_id: str) -> tuple[str, str]:
    """
    Identify which entry table an item_id belongs to.

    Returns (table_name, foreign_key_column).
    Raises ValueError when item_id is not found in any leaf table.
    """
    checks = [
        ("nw_cash_accounts", "nw_cash_entries",  "account_id"),
        ("nw_inv_holdings",  "nw_inv_entries",   "holding_id"),
        ("nw_asset_items",   "nw_asset_entries",  "item_id"),
    ]
    for owner_table, entry_table, fk_col in checks:
        if conn.execute(
                f"SELECT 1 FROM {owner_table} WHERE id = ?", (item_id,)
        ).fetchone():
            return entry_table, fk_col
    raise ValueError(f"No networth leaf item found with id={item_id!r}")


def upsert_networth_cell(
        item_id: str, year: int, month_idx: int, value: Optional[float]
) -> None:
    """
    Save (or clear) one monthly value cell.  Works for cash accounts,
    investment holdings, and asset items with a single unified call.
    Raises ValueError if item_id doesn't exist.
    """
    with _db() as conn:
        table, fk_col = _resolve_item_type(conn, item_id)
        if value is None:
            conn.execute(
                f"DELETE FROM {table} WHERE {fk_col} = ? AND year = ? AND month_idx = ?",
                (item_id, year, month_idx),
            )
        else:
            conn.execute(
                f"INSERT INTO {table} (id, {fk_col}, year, month_idx, value) "
                f"VALUES (?, ?, ?, ?, ?) "
                f"ON CONFLICT({fk_col}, year, month_idx) DO UPDATE SET value = excluded.value",
                (_uid(), item_id, year, month_idx, value),
            )


# ═════════════════════════════════════════════════════════════════════════════
#  BUDGET TARGETS
# ═════════════════════════════════════════════════════════════════════════════

def get_budget_categories() -> list[dict]:
    """
    All expense categories joined with their planning budget target.
    Categories without a target row have monthly_budget = None.
    """
    with _db() as conn:
        rows = conn.execute("""
                            SELECT   c.id, c.name, t.monthly_budget
                            FROM     cf_expense_categories c
                                         LEFT JOIN budget_targets t ON t.category_id = c.id
                            ORDER BY c.rowid
                            """).fetchall()
        return [
            {
                "id":             r["id"],
                "name":           r["name"],
                "monthly_budget": r["monthly_budget"],
            }
            for r in rows
        ]


def upsert_budget_target(category_id: str, monthly_budget: Optional[float]) -> None:
    with _db() as conn:
        if monthly_budget is None:
            conn.execute(
                "DELETE FROM budget_targets WHERE category_id = ?", (category_id,)
            )
        else:
            conn.execute(
                "INSERT INTO budget_targets (category_id, monthly_budget) VALUES (?, ?) "
                "ON CONFLICT(category_id) DO UPDATE SET monthly_budget = excluded.monthly_budget",
                (category_id, monthly_budget),
            )
