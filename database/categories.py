"""Category tree: read, create, rename, delete, reorder, move."""

from sqlalchemy import select, update
from database.base import NotFound, SessionLocal, add_child, add_root, require_root, roots
from database.models import (AssetCategory, AssetItem, Brokerage, CashAccount, CashInstitution,
                             ExpenseCategory, ExpenseSubcategory, Holding, IncomeCategory,
                             LiabilityCategory, LiabilityItem)

# kind → (root model, child model, child→root fk, child's display column)
KINDS = {
    "income":     (IncomeCategory,    None,               None,             None),
    "expense":    (ExpenseCategory,   ExpenseSubcategory, "category_id",    "name"),
    "cash":       (CashInstitution,   CashAccount,        "institution_id", "name"),
    "investment": (Brokerage,         Holding,            "brokerage_id",   "ticker"),
    "asset":      (AssetCategory,     AssetItem,          "category_id",    "name"),
    "liability":  (LiabilityCategory, LiabilityItem,      "category_id",    "name"),
}


def get_tree(user_id: str) -> dict:
    with SessionLocal.begin() as s:
        out = {}
        for kind, (root, child, fk, label) in KINDS.items():
            parents, kids = roots(s, root, user_id), {}
            if child:
                for k in s.scalars(select(child).where(getattr(child, fk).in_([p.id for p in parents]))
                                           .order_by(child.sort_order, getattr(child, label))):
                    kids.setdefault(getattr(k, fk), []).append({"id": k.id, "name": getattr(k, label)})
            out[kind] = [{"id": p.id, "name": p.name, "children": kids.get(p.id, [])} for p in parents]
        return out


def _find(s, kind, user_id, item_id):
    """The user's root or child row with this id."""
    root, child, fk, _ = KINDS[kind]
    row = s.scalar(select(root).where(root.id == item_id, root.user_id == user_id))
    if row is None and child:
        row = s.scalar(select(child).join(root, getattr(child, fk) == root.id)
                       .where(child.id == item_id, root.user_id == user_id))
    if row is None:
        raise NotFound(item_id)
    return row


def create(user_id, kind, name, parent_id):
    root, child, fk, label = KINDS[kind]
    if parent_id is None:
        return add_root(root, user_id, name)
    if child is None:
        raise NotFound(parent_id)
    return add_child(user_id, child, fk, root, parent_id,
                     **{label: name[:32] if label == "ticker" else name})


def rename(user_id, kind, item_id, name):
    with SessionLocal.begin() as s:
        row = _find(s, kind, user_id, item_id)
        label = "name" if isinstance(row, KINDS[kind][0]) else KINDS[kind][3]
        setattr(row, label, name[:32] if label == "ticker" else name)


def delete(user_id, kind, item_id):
    with SessionLocal.begin() as s:
        s.delete(_find(s, kind, user_id, item_id))     # DB cascades to children + entries


def arrange(user_id, kind, parent_id, ids):
    """Put `ids` under `parent_id` (None = top level) in this order. Children from another
    parent are re-parented: only the parent FK changes, so their entries move with them."""
    root, child, fk, _ = KINDS[kind]
    with SessionLocal.begin() as s:
        if parent_id is None:
            model, owned = root, select(root.id).where(root.user_id == user_id)
        else:
            if child is None:
                raise NotFound(parent_id)
            require_root(s, root, parent_id, user_id)
            model, owned = child, (select(child.id).join(root, getattr(child, fk) == root.id)
                                   .where(root.user_id == user_id))
        if set(s.scalars(owned.where(model.id.in_(ids)))) != set(ids):
            raise NotFound("ids")
        for i, rid in enumerate(ids):
            s.execute(update(model).where(model.id == rid)
                      .values(sort_order=i, **({fk: parent_id} if parent_id else {})))
