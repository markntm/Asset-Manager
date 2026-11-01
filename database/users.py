"""Create, Look-up Users"""

from typing import Optional
from sqlalchemy import select
from database.base import SessionLocal
from database.models import User
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError


def create_user(email: str, password_hash: str) -> Optional[str]:
    try:
        with SessionLocal.begin() as s:
            user = User(email=email.strip().lower(), password_hash=password_hash)
            s.add(user)
            s.flush()
            return user.id
    except IntegrityError:
        return None


def get_user_by_email(email: str) -> Optional[dict]:
    with SessionLocal.begin() as s:
        u = s.scalar(select(User).where(User.email == email.strip().lower()))
        return {"id": u.id, "email": u.email, "password_hash": u.password_hash,
                "locked_until": u.locked_until} if u else None

def record_failed_login(user_id: str, max_attempts: int = 5, lock_minutes: int = 15) -> None:
    with SessionLocal.begin() as s:
        u = s.get(User, user_id)
        u.failed_attempts += 1
        if u.failed_attempts >= max_attempts:
            u.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)
            u.failed_attempts = 0


def clear_failed_logins(user_id: str) -> None:
    with SessionLocal.begin() as s:
        u = s.get(User, user_id)
        u.failed_attempts = 0
        u.locked_until = None
