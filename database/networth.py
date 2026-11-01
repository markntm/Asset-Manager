"""Cash, Investments, Assets Functions"""

from collections import defaultdict
from decimal import Decimal
from sqlalchemy import select, update
from database.base import (NotFound, SessionLocal, add_child, add_root, cells, delete_child,
                           delete_root, require_child, roots, upsert_cell)
from database.models import (AssetCategory, AssetEntry, AssetItem, Brokerage, CashAccount,
                             CashEntry, CashInstitution, Holding, InvEntry)

# (leaf table, fk to parent, parent table, entry table, fk in entry table)
_LEAVES = (
    (CashAccount, "institution_id", CashInstitution, CashEntry, "account_id"),
    (Holding,     "brokerage_id",   Brokerage,       InvEntry,  "holding_id"),
    (AssetItem,   "category_id",    AssetCategory,   AssetEntry, "item_id"),
)


def _tree(s, user_id, year, Root, Child, child_fk, Entry, entry_fk, key, order, fields=("name",)):
    parents = roots(s, Root, user_id)
    kids = s.scalars(select(Child)
                     .where(getattr(Child, child_fk).in_([p.id for p in parents]))
                     .order_by(order)).all()
    vals = cells(s, Entry, entry_fk, [k.id for k in kids], year)
    by_parent = defaultdict(list)
    for k in kids:
        item = {"id": k.id, "values": vals[k.id]}
        for f in fields:
            v = getattr(k, f)
            item[f] = float(v) if isinstance(v, Decimal) else v
        by_parent[getattr(k, child_fk)].append(item)
    return [{"id": p.id, "name": p.name, key: by_parent[p.id]} for p in parents]


def get_networth_data(user_id: str, year: int) -> dict:
    with SessionLocal.begin() as s:
        return {
            "cash": _tree(s, user_id, year, CashInstitution, CashAccount, "institution_id",
                          CashEntry, "account_id", "accounts", CashAccount.name),
            "investments": _tree(s, user_id, year, Brokerage, Holding, "brokerage_id",
                                 InvEntry, "holding_id", "holdings", Holding.ticker,
                                 ("ticker", "quantity")),
            "assets": _tree(s, user_id, year, AssetCategory, AssetItem, "category_id",
                            AssetEntry, "item_id", "items", AssetItem.name),
        }


# ── Cash ──
def add_cash_institution(user_id, name):
    return add_root(CashInstitution, user_id, name)

def add_cash_account(user_id, institution_id, name):
    return add_child(user_id, CashAccount, "institution_id", CashInstitution, institution_id, name=name)

def delete_cash_institution(user_id, institution_id):
    delete_root(CashInstitution, user_id, institution_id)

def delete_cash_account(user_id, account_id):
    delete_child(user_id, CashAccount, "institution_id", CashInstitution, account_id)


# ── Investments ──
def add_brokerage(user_id, name):
    return add_root(Brokerage, user_id, name)

def add_holding(user_id, brokerage_id, ticker, quantity):
    return add_child(user_id, Holding, "brokerage_id", Brokerage, brokerage_id,
                     ticker=ticker, quantity=quantity)

def update_holding_quantity(user_id, holding_id, quantity):
    with SessionLocal.begin() as s:
        require_child(s, Holding, "brokerage_id", Brokerage, holding_id, user_id)
        s.execute(update(Holding).where(Holding.id == holding_id).values(quantity=quantity))

def delete_brokerage(user_id, brokerage_id):
    delete_root(Brokerage, user_id, brokerage_id)

def delete_holding(user_id, holding_id):
    delete_child(user_id, Holding, "brokerage_id", Brokerage, holding_id)


# ── Assets ──
def add_asset_category(user_id, name):
    return add_root(AssetCategory, user_id, name)

def add_asset_item(user_id, category_id, name):
    return add_child(user_id, AssetItem, "category_id", AssetCategory, category_id, name=name)

def delete_asset_category(user_id, category_id):
    delete_root(AssetCategory, user_id, category_id)

def delete_asset_item(user_id, item_id):
    delete_child(user_id, AssetItem, "category_id", AssetCategory, item_id)


# ── Unified cell save ──
def upsert_networth_cell(user_id, item_id, year, month_idx, value):
    with SessionLocal.begin() as s:
        for leaf, fk, root, entry, entry_fk in _LEAVES:
            try:
                require_child(s, leaf, fk, root, item_id, user_id)
            except NotFound:
                continue
            upsert_cell(s, entry, entry_fk, item_id, year, month_idx, value)
            return
        raise NotFound(item_id)
