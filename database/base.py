"""Engine, Session Factory"""

import os
from collections import defaultdict
from dotenv import load_dotenv
from sqlalchemy import create_engine, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

load_dotenv(".env.loc")   # local dev only; no-op on Vercel


class NotFound(LookupError):
    """Row missing OR owned by another user. Both become a 404."""


def pg_url(var: str = "DATABASE_URL") -> str:
    return os.environ[var].replace("postgresql://", "postgresql+psycopg://", 1)


# NullPool: Neon's pooler already pools. prepare_threshold=None: PgBouncer-safe.
engine = create_engine(pg_url(), poolclass=NullPool, connect_args={"prepare_threshold": None})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


# ── Shared query helpers ─────────────────────────────────────────────────────

def roots(s, model, user_id):
    """A user's top-level rows, oldest first."""
    return s.scalars(select(model).where(model.user_id == user_id).order_by(model.created_at)).all()


def require_root(s, model, row_id, user_id):
    if s.scalar(select(model.id).where(model.id == row_id, model.user_id == user_id)) is None:
        raise NotFound(row_id)


def require_child(s, child, fk_name, parent, row_id, user_id):
    q = (select(child.id)
         .join(parent, getattr(child, fk_name) == parent.id)
         .where(child.id == row_id, parent.user_id == user_id))
    if s.scalar(q) is None:
        raise NotFound(row_id)


def add_root(model, user_id, name) -> dict:
    with SessionLocal.begin() as s:
        row = model(user_id=user_id, name=name)
        s.add(row)
        s.flush()
        return {"id": row.id, "name": name}


def delete_root(model, user_id, row_id) -> None:
    with SessionLocal.begin() as s:
        s.execute(delete(model).where(model.id == row_id, model.user_id == user_id))


def add_child(user_id, child, fk_name, parent, parent_id, **fields) -> dict:
    with SessionLocal.begin() as s:
        require_root(s, parent, parent_id, user_id)
        row = child(**{fk_name: parent_id}, **fields)
        s.add(row)
        s.flush()
        return {"id": row.id, **fields}


def delete_child(user_id, child, fk_name, parent, row_id) -> None:
    with SessionLocal.begin() as s:
        require_child(s, child, fk_name, parent, row_id, user_id)
        s.execute(delete(child).where(child.id == row_id))


def cells(s, model, fk_name, parent_ids, year) -> dict:
    """{parent_id: {"0": float, ...}} for one entry table and year, in one query."""
    fk = getattr(model, fk_name)
    out = defaultdict(dict)
    for pid, mi, val in s.execute(
            select(fk, model.month_idx, model.value).where(fk.in_(parent_ids), model.year == year)
    ):
        out[pid][str(mi)] = float(val)
    return out


def upsert_cell(s, model, fk_name, parent_id, year, month_idx, value) -> None:
    fk = getattr(model, fk_name)
    if value is None:
        s.execute(delete(model).where(fk == parent_id, model.year == year, model.month_idx == month_idx))
        return
    stmt = insert(model).values({fk_name: parent_id, "year": year, "month_idx": month_idx, "value": value})
    s.execute(stmt.on_conflict_do_update(
        index_elements=[fk_name, "year", "month_idx"], set_={"value": stmt.excluded.value}))
