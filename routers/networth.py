"""
routers/networth.py  —  All /api/networth/* endpoints.

Every cell-save returns the full compute_networth_summary payload so the
frontend can apply all derived values (deltas, chart series, allocation %)
without any local recalculation.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends

from auth import current_user_id
from database import networth as db
from calculations.networth import compute_networth_summary
from schemas import HoldingIn, HoldingQtyIn, NameIn, NwCellIn

router = APIRouter(tags=["networth"])


# ── Year data load ────────────────────────────────────────────────────────────

@router.get("/data/{year}")
def get_networth_data(year: int, user_id: str = Depends(current_user_id)):
    return db.get_networth_data(user_id, year)


# ── Unified cell save (cash accounts, holdings, asset items) ─────────────────

@router.put("/cells")
def put_networth_cell(body: NwCellIn, user_id: str = Depends(current_user_id)):
    try:
        db.upsert_networth_cell(user_id, body.item_id, body.year, body.month_idx, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    data = db.get_networth_data(user_id, body.year)
    return compute_networth_summary(
        data["cash"], data["investments"], data["assets"],
        body.year, body.month_idx,
    )


# ── Cash CRUD ─────────────────────────────────────────────────────────────────

@router.post("/cash/institutions", status_code=201)
def post_cash_institution(body: NameIn, user_id: str = Depends(current_user_id)):
    return db.add_cash_institution(user_id, body.name)


@router.post("/cash/institutions/{institution_id}/accounts", status_code=201)
def post_cash_account(institution_id: str, body: NameIn, user_id: str = Depends(current_user_id)):
    return db.add_cash_account(user_id, institution_id, body.name)


@router.delete("/cash/institutions/{institution_id}", status_code=204)
def delete_cash_institution(institution_id: str, user_id: str = Depends(current_user_id)):
    db.delete_cash_institution(user_id, institution_id)


@router.delete("/cash/accounts/{account_id}", status_code=204)
def delete_cash_account(account_id: str, user_id: str = Depends(current_user_id)):
    db.delete_cash_account(user_id, account_id)


# ── Investment CRUD ───────────────────────────────────────────────────────────

@router.post("/investments/brokerages", status_code=201)
def post_brokerage(body: NameIn, user_id: str = Depends(current_user_id)):
    return db.add_brokerage(user_id, body.name)


@router.post("/investments/brokerages/{brokerage_id}/holdings", status_code=201)
def post_holding(brokerage_id: str, body: HoldingIn, user_id: str = Depends(current_user_id)):
    return db.add_holding(user_id, brokerage_id, body.ticker, body.quantity)


@router.put("/investments/holdings/{holding_id}/quantity")
def put_holding_quantity(holding_id: str, body: HoldingQtyIn, user_id: str = Depends(current_user_id)):
    db.update_holding_quantity(user_id, holding_id, body.quantity)
    return {"ok": True}


@router.delete("/investments/brokerages/{brokerage_id}", status_code=204)
def delete_brokerage(brokerage_id: str, user_id: str = Depends(current_user_id)):
    db.delete_brokerage(user_id, brokerage_id)


@router.delete("/investments/holdings/{holding_id}", status_code=204)
def delete_holding(holding_id: str, user_id: str = Depends(current_user_id)):
    db.delete_holding(user_id, holding_id)


# ── Asset CRUD ────────────────────────────────────────────────────────────────

@router.post("/assets/categories", status_code=201)
def post_asset_category(body: NameIn, user_id: str = Depends(current_user_id)):
    return db.add_asset_category(user_id, body.name)


@router.post("/assets/categories/{category_id}/items", status_code=201)
def post_asset_item(category_id: str, body: NameIn, user_id: str = Depends(current_user_id)):
    return db.add_asset_item(user_id, category_id, body.name)


@router.delete("/assets/categories/{category_id}", status_code=204)
def delete_asset_category(category_id: str, user_id: str = Depends(current_user_id)):
    db.delete_asset_category(user_id, category_id)


@router.delete("/assets/items/{item_id}", status_code=204)
def delete_asset_item(item_id: str, user_id: str = Depends(current_user_id)):
    db.delete_asset_item(user_id, item_id)
