"""routers/transactions.py  —  /api/transactions/*"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from auth import current_user_id
from database import transactions as db
from schemas import TxnIn

router = APIRouter(tags=["transactions"])


def _fields(body: TxnIn) -> dict:
    f = body.model_dump()
    f["txn_date"] = f.pop("date")
    return f


@router.get("")
def list_transactions(user_id: str = Depends(current_user_id)):
    return db.get_transactions_page(user_id)


@router.post("", status_code=201)
def post_transaction(body: TxnIn, user_id: str = Depends(current_user_id)):
    try:
        return db.create_transaction(user_id, _fields(body))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.put("/{txn_id}")
def put_transaction(txn_id: str, body: TxnIn, user_id: str = Depends(current_user_id)):
    try:
        return db.update_transaction(user_id, txn_id, _fields(body))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.delete("/{txn_id}", status_code=204)
def delete_transaction(txn_id: str, user_id: str = Depends(current_user_id)):
    db.delete_transaction(user_id, txn_id)
