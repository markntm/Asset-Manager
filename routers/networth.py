"""
routers/networth.py  —  All /api/networth/* endpoints.

Every cell-save returns the full compute_networth_summary payload so the
frontend can apply all derived values (deltas, chart series, allocation %)
without any local recalculation.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import database.database as db
from calculations.networth import compute_networth_summary
from schemas import HoldingIn, HoldingQtyIn, NameIn, NwCellIn

router = APIRouter(tags=["networth"])


# ── Year data load ────────────────────────────────────────────────────────────

@router.get("/data/{year}")
def get_networth_data(year: int):
    return db.get_networth_data(year)


# ── Unified cell save (cash accounts, holdings, asset items) ─────────────────

@router.put("/cells")
def put_networth_cell(body: NwCellIn):
    try:
        db.upsert_networth_cell(body.item_id, body.year, body.month_idx, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    data = db.get_networth_data(body.year)
    return compute_networth_summary(
        data["cash"], data["investments"], data["assets"],
        body.year, body.month_idx,
    )


# ── Cash CRUD ─────────────────────────────────────────────────────────────────

@router.post("/cash/institutions", status_code=201)
def post_cash_institution(body: NameIn):
    return db.add_cash_institution(body.name)


@router.post("/cash/institutions/{institution_id}/accounts", status_code=201)
def post_cash_account(institution_id: str, body: NameIn):
    return db.add_cash_account(institution_id, body.name)


@router.delete("/cash/institutions/{institution_id}", status_code=204)
def delete_cash_institution(institution_id: str):
    db.delete_cash_institution(institution_id)


@router.delete("/cash/accounts/{account_id}", status_code=204)
def delete_cash_account(account_id: str):
    db.delete_cash_account(account_id)


# ── Investment CRUD ───────────────────────────────────────────────────────────

@router.post("/investments/brokerages", status_code=201)
def post_brokerage(body: NameIn):
    return db.add_brokerage(body.name)


@router.post("/investments/brokerages/{brokerage_id}/holdings", status_code=201)
def post_holding(brokerage_id: str, body: HoldingIn):
    return db.add_holding(brokerage_id, body.ticker, body.quantity)


@router.put("/investments/holdings/{holding_id}/quantity")
def put_holding_quantity(holding_id: str, body: HoldingQtyIn):
    db.update_holding_quantity(holding_id, body.quantity)
    return {"ok": True}


@router.delete("/investments/brokerages/{brokerage_id}", status_code=204)
def delete_brokerage(brokerage_id: str):
    db.delete_brokerage(brokerage_id)


@router.delete("/investments/holdings/{holding_id}", status_code=204)
def delete_holding(holding_id: str):
    db.delete_holding(holding_id)


# ── Asset CRUD ────────────────────────────────────────────────────────────────

@router.post("/assets/categories", status_code=201)
def post_asset_category(body: NameIn):
    return db.add_asset_category(body.name)


@router.post("/assets/categories/{category_id}/items", status_code=201)
def post_asset_item(category_id: str, body: NameIn):
    return db.add_asset_item(category_id, body.name)


@router.delete("/assets/categories/{category_id}", status_code=204)
def delete_asset_category(category_id: str):
    db.delete_asset_category(category_id)


@router.delete("/assets/items/{item_id}", status_code=204)
def delete_asset_item(item_id: str):
    db.delete_asset_item(item_id)
