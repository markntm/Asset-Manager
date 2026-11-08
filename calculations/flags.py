"""calculations/flags.py — derive transaction flags. Pure: dicts in, {txn_id: [flag, ...]} out."""
from collections import defaultdict
from statistics import mean, median, pstdev

from calculations.statements import merchant_key

HIGH_Z        = 2.0    # std-devs above the mean
MIN_CAT       = 5      # min txns in a subcategory to use its own stats
MIN_ALL       = 10     # min outflows overall before any flagging
NEW_MULT      = 1.5    # new merchant must exceed this × median outflow
RECUR_MONTHS  = 3
RECUR_TOL     = 0.10


def flag_transactions(txns: list[dict]) -> dict:
    out = [t for t in txns if t["amount"] < 0 and not t["is_transfer"]]
    if len(out) < MIN_ALL:
        return {}
    amt = lambda t: -t["amount"]
    all_amts = [amt(t) for t in out]
    med = median(all_amts)

    by_cat, by_mer = defaultdict(list), defaultdict(list)
    for t in out:
        if t["expense_subcategory_id"]:
            by_cat[t["expense_subcategory_id"]].append(amt(t))
        if key := merchant_key(t["merchant"]):
            by_mer[key].append(t)

    flags = defaultdict(list)

    for t in out:
        vals = by_cat.get(t["expense_subcategory_id"])
        vals = vals if vals and len(vals) >= MIN_CAT else all_amts
        if amt(t) > mean(vals) + HIGH_Z * pstdev(vals):
            flags[t["id"]].append("high")

    for ts in by_mer.values():
        if len(ts) == 1 and amt(ts[0]) > NEW_MULT * med:
            flags[ts[0]["id"]].append("new_merchant")
        if len({t["date"][:7] for t in ts}) >= RECUR_MONTHS:
            m = median(amt(t) for t in ts)
            for t in ts:
                if abs(amt(t) - m) <= RECUR_TOL * m:
                    flags[t["id"]].append("recurring")

    return dict(flags)
