# auth.py: TEMPORARY. Replaced by real session auth in the next step.
import os
from fastapi import HTTPException


def current_user_id() -> str:
    uid = os.environ.get("DEV_USER_ID")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return uid
