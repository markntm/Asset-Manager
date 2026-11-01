"""routers/account.py  —  /api/auth/* (signup, login)."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

import database.users as users
from auth import DUMMY_HASH, hash_password, verify_password
from schemas import AuthIn

router = APIRouter(tags=["account"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _start_session(request: Request, user_id: str) -> None:
    request.session.clear()          # drop any pre-existing session data
    request.session["uid"] = user_id


@router.post("/signup", status_code=201)
def signup(body: AuthIn, request: Request):
    if os.environ.get("ALLOW_SIGNUP", "").lower() != "true":
        raise HTTPException(403, "Sign-ups are currently closed.")
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    if len(body.password) < 10:
        raise HTTPException(422, "Password must be at least 10 characters.")
    user_id = users.create_user(email, hash_password(body.password))
    if user_id is None:
        raise HTTPException(409, "An account with that email already exists.")
    _start_session(request, user_id)
    return {"ok": True}


@router.post("/login")
def login(body: AuthIn, request: Request):
    user = users.get_user_by_email(body.email)
    if user and user["locked_until"] and user["locked_until"] > datetime.now(timezone.utc):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    ok = verify_password(user["password_hash"] if user else DUMMY_HASH, body.password)
    if not user or not ok:
        if user:
            users.record_failed_login(user["id"])
        raise HTTPException(401, "Invalid email or password.")
    users.clear_failed_logins(user["id"])
    _start_session(request, user["id"])
    return {"ok": True}
