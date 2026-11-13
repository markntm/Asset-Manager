"""routers/categories.py  —  /api/categories/*  (cash flow + net worth category tree)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from auth import current_user_id
from database import categories as db
from schemas import ArrangeIn, CategoryIn

router = APIRouter(tags=["categories"])


def _kind(kind: str) -> str:
    if kind not in db.KINDS:
        raise HTTPException(404, "Unknown category type.")
    return kind


@router.get("")
def get_tree(user_id: str = Depends(current_user_id)):
    return db.get_tree(user_id)


@router.post("/{kind}/arrange")
def arrange(kind: str, body: ArrangeIn, user_id: str = Depends(current_user_id)):
    db.arrange(user_id, _kind(kind), body.parent_id, body.ids)
    return {"ok": True}


@router.post("/{kind}", status_code=201)
def create(kind: str, body: CategoryIn, user_id: str = Depends(current_user_id)):
    return db.create(user_id, _kind(kind), body.name.strip(), body.parent_id)


@router.put("/{kind}/{item_id}")
def rename(kind: str, item_id: str, body: CategoryIn, user_id: str = Depends(current_user_id)):
    db.rename(user_id, _kind(kind), item_id, body.name.strip())
    return {"ok": True}


@router.delete("/{kind}/{item_id}", status_code=204)
def delete(kind: str, item_id: str, user_id: str = Depends(current_user_id)):
    db.delete(user_id, _kind(kind), item_id)
