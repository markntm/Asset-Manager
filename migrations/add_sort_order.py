"""One-off: add sort_order to every category table, keeping today's display order.
Run from the project root:  python -m migrations.add_sort_order
Safe to re-run: tables that already have the column are skipped."""
from sqlalchemy import inspect, text
from database.base import engine

# (table, column it's grouped by, column it's currently ordered by)
TABLES = [
    ("cf_income_categories",     "user_id",        "created_at"),
    ("cf_expense_categories",    "user_id",        "created_at"),
    ("nw_cash_institutions",     "user_id",        "created_at"),
    ("nw_inv_brokerages",        "user_id",        "created_at"),
    ("nw_asset_categories",      "user_id",        "created_at"),
    ("nw_liability_categories",  "user_id",        "created_at"),
    ("cf_expense_subcategories", "category_id",    "name"),
    ("nw_cash_accounts",         "institution_id", "name"),
    ("nw_inv_holdings",          "brokerage_id",   "ticker"),
    ("nw_asset_items",           "category_id",    "name"),
    ("nw_liability_items",       "category_id",    "name"),
]

with engine.begin() as c:   # one transaction: every table changes or none does
    insp = inspect(c)
    for tbl, grp, order in TABLES:
        if any(col["name"] == "sort_order" for col in insp.get_columns(tbl)):
            print("skip    ", tbl)
            continue
        c.execute(text(f"ALTER TABLE {tbl} ADD COLUMN sort_order integer NOT NULL DEFAULT 0"))
        c.execute(text(f"UPDATE {tbl} t SET sort_order = s.rn FROM "
                       f"(SELECT id, row_number() OVER (PARTITION BY {grp} ORDER BY {order}) rn FROM {tbl}) s "
                       f"WHERE t.id = s.id"))
        print("migrated", tbl)
