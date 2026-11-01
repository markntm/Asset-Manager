"""Create, Look-up Users"""

from typing import Optional
from sqlalchemy import select
from database.base import SessionLocal
from database.models import User


def create_user(email: str, password_hash: str) -> str:
    with SessionLocal.begin() as s:
        user = User(email=email.strip().lower(), password_hash=password_hash)
        s.add(user)
        s.flush()
        return user.id


def get_user_by_email(email: str) -> Optional[dict]:
    with SessionLocal.begin() as s:
        u = s.scalar(select(User).where(User.email == email.strip().lower()))
        return {"id": u.id, "email": u.email, "password_hash": u.password_hash} if u else None
