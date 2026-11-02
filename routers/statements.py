"""routers/statements.py  —  /api/statements/*   parse → review → commit.
Uploaded files are processed in memory only; nothing about the file is ever written to disk or the DB
(only the totals/checksum of a committed import are kept)."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from auth import current_user_id
from calculations import statements as stmt
from database import statements as db
from schemas import StmtCheckIn, StmtCommitIn

router = APIRouter(tags=["statements"])
MAX_BYTES = 4 * 1024 * 1024          # Vercel rejects request bodies over ~4.5 MB
TYPES = {"checking", "savings", "credit", "venmo", "other"}


@router.post("/parse")
def parse_statement(file: UploadFile = File(...), mapping: Optional[str] = Form(None),
                    statement_type: Optional[str] = Form(None), user_id: str = Depends(current_user_id)):
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 4 MB.")
    stype = statement_type if statement_type in TYPES else None
    name = (file.filename or "").lower()
    ctx = db.get_lookups(user_id)
    try:
        if data[:5] == b"%PDF-":
            parsed = stmt.parse_pdf(data, name, ctx["banks"], stype)
        elif name.endswith((".csv", ".tsv", ".txt")):
            parsed = stmt.parse_csv(data, name, ctx["banks"], json.loads(mapping) if mapping else None, stype)
        else:
            raise HTTPException(415, "Unsupported file type — drop a PDF or CSV.")
    except stmt.StatementError as exc:
        raise HTTPException(422, str(exc))
    except json.JSONDecodeError:
        raise HTTPException(422, "Invalid column mapping.")
    return db.enrich(user_id, parsed, ctx)


@router.post("/check")
def check_duplicates(body: StmtCheckIn, user_id: str = Depends(current_user_id)):
    return {"duplicates": db.check_duplicates(user_id, body.bank_id, [(r.date, r.amount) for r in body.rows])}


@router.post("/commit")
def commit(body: StmtCommitIn, user_id: str = Depends(current_user_id)):
    if not body.rows:
        raise HTTPException(422, "Nothing to import.")
    try:
        return db.commit_statement(user_id, body.meta.model_dump(), [r.model_dump() for r in body.rows])
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/imports")
def imports(user_id: str = Depends(current_user_id)):
    return {"imports": db.list_imports(user_id)}
