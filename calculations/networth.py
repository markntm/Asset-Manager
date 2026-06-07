"""
calculations/networth.py  ·  v2
────────────────────────────────────────────────────────────────────────────
Pure, stateless calculation functions for the Net Worth module.

Redesigned for a 3-level hierarchy:
    Cash        → institutions  → accounts
    Investments → brokerages    → holdings  (ticker + quantity)
    Assets      → categories    → items

All functions accept plain dicts / lists as returned by database.py.
No I/O, no FastAPI imports — fully unit-testable in isolation.

Expected DB shapes
──────────────────
cash_inst : {
    "id": str, "name": str,
    "accounts": [
        { "id": str, "name": str, "values": { "0": float, … } }
    ]
}

inv_brk : {
    "id": str, "name": str,
    "holdings": [
        { "id": str, "ticker": str, "quantity": float,
          "values": { "0": float, … } }
        # values = manually-entered monthly market value
        # Future: values auto-computed as quantity × fetch_price(ticker, date)
    ]
}

ast_cat : {
    "id": str, "name": str,
    "items": [
        { "id": str, "name": str, "values": { "0": float, … } }
    ]
}

Keys in values dicts may be str ("0"…"11") or int; _get() handles both.
Month indices are always int 0–11.
"""
from __future__ import annotations
from typing import Optional


# ════════════════════════════════════════════════════════════════════
#  PRIVATE HELPERS
# ════════════════════════════════════════════════════════════════════

def _get(mapping: dict, month_idx: int) -> float:
    """
    Fetch a monthly value stored under either a str or int key.
    Returns 0.0 when absent — absence means $0 for arithmetic purposes;
    the frontend controls blank-vs-zero display separately.
    """
    v = mapping.get(str(month_idx))
    if v is None:
        v = mapping.get(month_idx)
    return float(v) if v is not None else 0.0


def _prev(month_idx: int) -> Optional[int]:
    """Previous month index, or None for January."""
    return month_idx - 1 if month_idx > 0 else None


# ════════════════════════════════════════════════════════════════════
#  CASH
# ════════════════════════════════════════════════════════════════════

def cash_account_value(account: dict, month_idx: int) -> float:
    """Single cash account balance for one month."""
    return _get(account["values"], month_idx)


def cash_institution_total(institution: dict, month_idx: int) -> float:
    """Sum of all account balances within one institution for one month."""
    return round(
        sum(_get(a["values"], month_idx) for a in institution.get("accounts", [])), 2
    )


def cash_month_total(institutions: list[dict], month_idx: int) -> float:
    """Sum across all cash institutions for one month."""
    return round(sum(cash_institution_total(i, month_idx) for i in institutions), 2)


def cash_year_series(institutions: list[dict]) -> list[float]:
    """Monthly cash totals for all 12 months. Consumed by the line chart."""
    return [cash_month_total(institutions, mi) for mi in range(12)]


# ════════════════════════════════════════════════════════════════════
#  INVESTMENTS
# ════════════════════════════════════════════════════════════════════

def inv_holding_value(holding: dict, month_idx: int) -> float:
    """
    Single holding's value for one month.

    Currently uses manually-entered values.
    Future: replace with holding["quantity"] * fetch_market_price(holding["ticker"], date)
    when the market price API is connected. The ticker and quantity fields
    are already stored per holding to support this integration.
    """
    return _get(holding["values"], month_idx)


def inv_brokerage_total(brokerage: dict, month_idx: int) -> float:
    """Sum of all holding values within one brokerage for one month."""
    return round(
        sum(_get(h["values"], month_idx) for h in brokerage.get("holdings", [])), 2
    )


def inv_month_total(brokerages: list[dict], month_idx: int) -> float:
    """Sum across all investment brokerages for one month."""
    return round(sum(inv_brokerage_total(b, month_idx) for b in brokerages), 2)


def inv_year_series(brokerages: list[dict]) -> list[float]:
    """Monthly investment totals for all 12 months. Consumed by the line chart."""
    return [inv_month_total(brokerages, mi) for mi in range(12)]


# ════════════════════════════════════════════════════════════════════
#  ASSETS
# ════════════════════════════════════════════════════════════════════

def ast_item_value(item: dict, month_idx: int) -> float:
    """Single asset item's value for one month."""
    return _get(item["values"], month_idx)


def ast_category_total(category: dict, month_idx: int) -> float:
    """Sum of all item values within one asset category for one month."""
    return round(
        sum(_get(i["values"], month_idx) for i in category.get("items", [])), 2
    )


def ast_month_total(categories: list[dict], month_idx: int) -> float:
    """Sum across all asset categories for one month."""
    return round(sum(ast_category_total(c, month_idx) for c in categories), 2)


def ast_year_series(categories: list[dict]) -> list[float]:
    """Monthly asset totals for all 12 months. Consumed by the line chart."""
    return [ast_month_total(categories, mi) for mi in range(12)]


# ════════════════════════════════════════════════════════════════════
#  NET WORTH TOTALS
# ════════════════════════════════════════════════════════════════════

def net_worth_month_total(
        cash: list[dict], investments: list[dict], assets: list[dict],
        month_idx: int,
) -> float:
    """Combined net worth across all three groups for one month."""
    return round(
        cash_month_total(cash, month_idx)
        + inv_month_total(investments, month_idx)
        + ast_month_total(assets, month_idx),
        2,
        )


def net_worth_year_series(
        cash: list[dict], investments: list[dict], assets: list[dict]
) -> list[float]:
    """
    Monthly net worth totals for all 12 months.
    Consumed by the Net Worth Trend line chart dataset.
    """
    return [net_worth_month_total(cash, investments, assets, mi) for mi in range(12)]


# ════════════════════════════════════════════════════════════════════
#  LATEST FILLED MONTH
# ════════════════════════════════════════════════════════════════════

def latest_filled_month(
        cash: list[dict], investments: list[dict], assets: list[dict]
) -> Optional[int]:
    """
    Returns the highest month index (0–11) that has at least one non-zero
    value across any leaf node in any group.
    Returns None if no data has been entered for the year.
    """
    all_value_maps: list[dict] = []
    for inst in cash:
        for acc in inst.get("accounts", []):
            all_value_maps.append(acc.get("values", {}))
    for brk in investments:
        for h in brk.get("holdings", []):
            all_value_maps.append(h.get("values", {}))
    for cat in assets:
        for item in cat.get("items", []):
            all_value_maps.append(item.get("values", {}))

    for mi in range(11, -1, -1):
        if any(_get(vm, mi) != 0.0 for vm in all_value_maps):
            return mi
    return None


# ════════════════════════════════════════════════════════════════════
#  MONTH-OVER-MONTH CHANGES
# ════════════════════════════════════════════════════════════════════

def mom_change(current: float, previous: Optional[float]) -> Optional[float]:
    """
    Signed dollar change vs the previous month.
    Returns None when previous is None so the frontend renders "—".
    """
    if previous is None:
        return None
    return round(current - previous, 2)


def mom_pct_change(current: float, previous: Optional[float]) -> Optional[float]:
    """
    Percentage change vs the previous month.
    Returns None when previous is None or zero to avoid division errors.
    """
    if previous is None or previous == 0.0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


# ════════════════════════════════════════════════════════════════════
#  ALLOCATION
# ════════════════════════════════════════════════════════════════════

def allocation_at_month(
        cash: list[dict], investments: list[dict], assets: list[dict],
        month_idx: int,
) -> dict:
    """
    Per-group dollar amounts and percentage share of net worth at one month.
    Percentages are None when net worth is zero.

    Returns:
        {
            "cash":        { "amount": float, "pct": float | None },
            "investments": { "amount": float, "pct": float | None },
            "assets":      { "amount": float, "pct": float | None },
        }
    """
    c = cash_month_total(cash, month_idx)
    i = inv_month_total(investments, month_idx)
    a = ast_month_total(assets, month_idx)
    nw = c + i + a
    def pct(v: float) -> Optional[float]:
        return round(v / nw * 100, 2) if nw > 0 else None
    return {
        "cash":        {"amount": c, "pct": pct(c)},
        "investments": {"amount": i, "pct": pct(i)},
        "assets":      {"amount": a, "pct": pct(a)},
    }


# ════════════════════════════════════════════════════════════════════
#  PATTERN A — FULL RESPONSE AFTER ANY CELL SAVE
# ════════════════════════════════════════════════════════════════════

def compute_networth_summary(
        cash:        list[dict],
        investments: list[dict],
        assets:      list[dict],
        year:        int,
        month_idx:   int,
) -> dict:
    """
    Compute every number visible on the net worth page after any cell is
    saved.  Called by main.py immediately after db.upsert_networth_cell().

    month_idx is the month the user just edited; all deltas are computed
    relative to month_idx - 1.

    Return shape
    ────────────
    {
        "year":        int,
        "month_idx":   int,
        "latest_month_idx": int | None,

        # Summary cards
        "summary": {
            "cash": float, "investments": float, "assets": float,
            "net_worth": float,
            "cash_delta": float|None, "investments_delta": float|None,
            "assets_delta": float|None, "nw_delta": float|None,
            "nw_pct_delta": float|None,
            "cash_pct": float|None, "investments_pct": float|None,
            "assets_pct": float|None,
        },

        # Institution / brokerage / category subtotals for this month
        "cash_inst_totals":  { inst_id:  float },
        "cash_inst_deltas":  { inst_id:  float | None },
        "inv_brk_totals":    { brk_id:   float },
        "inv_brk_deltas":    { brk_id:   float | None },
        "ast_cat_totals":    { cat_id:   float },
        "ast_cat_deltas":    { cat_id:   float | None },

        # Leaf-level deltas (values already held in browser STATE)
        "cash_acc_deltas":   { acc_id:  float | None },
        "inv_hold_deltas":   { hold_id: float | None },
        "ast_item_deltas":   { item_id: float | None },

        # Full-year series for chart updates
        "net_worth_series":  [float × 12],
        "group_series": {
            "cash":        [float × 12],
            "investments": [float × 12],
            "assets":      [float × 12],
        },
    }
    """
    pmi = _prev(month_idx)

    # ── Group totals at current and previous month ────────────────
    c_cur  = cash_month_total(cash, month_idx)
    i_cur  = inv_month_total(investments, month_idx)
    a_cur  = ast_month_total(assets, month_idx)
    nw_cur = round(c_cur + i_cur + a_cur, 2)

    c_prv  = cash_month_total(cash, pmi)          if pmi is not None else None
    i_prv  = inv_month_total(investments, pmi)    if pmi is not None else None
    a_prv  = ast_month_total(assets, pmi)         if pmi is not None else None
    nw_prv = round(c_prv + i_prv + a_prv, 2)     if pmi is not None else None

    alloc = allocation_at_month(cash, investments, assets, month_idx)

    summary = {
        "cash":               c_cur,
        "investments":        i_cur,
        "assets":             a_cur,
        "net_worth":          nw_cur,
        "cash_delta":         mom_change(c_cur,  c_prv),
        "investments_delta":  mom_change(i_cur,  i_prv),
        "assets_delta":       mom_change(a_cur,  a_prv),
        "nw_delta":           mom_change(nw_cur, nw_prv),
        "nw_pct_delta":       mom_pct_change(nw_cur, nw_prv),
        "cash_pct":           alloc["cash"]["pct"],
        "investments_pct":    alloc["investments"]["pct"],
        "assets_pct":         alloc["assets"]["pct"],
    }

    # ── Institution-level totals + deltas ─────────────────────────
    cash_inst_totals, cash_inst_deltas = {}, {}
    for inst in cash:
        t = cash_institution_total(inst, month_idx)
        p = cash_institution_total(inst, pmi) if pmi is not None else None
        cash_inst_totals[inst["id"]] = t
        cash_inst_deltas[inst["id"]] = mom_change(t, p)

    inv_brk_totals, inv_brk_deltas = {}, {}
    for brk in investments:
        t = inv_brokerage_total(brk, month_idx)
        p = inv_brokerage_total(brk, pmi) if pmi is not None else None
        inv_brk_totals[brk["id"]] = t
        inv_brk_deltas[brk["id"]] = mom_change(t, p)

    ast_cat_totals, ast_cat_deltas = {}, {}
    for cat in assets:
        t = ast_category_total(cat, month_idx)
        p = ast_category_total(cat, pmi) if pmi is not None else None
        ast_cat_totals[cat["id"]] = t
        ast_cat_deltas[cat["id"]] = mom_change(t, p)

    # ── Leaf-level deltas ─────────────────────────────────────────
    cash_acc_deltas = {}
    for inst in cash:
        for acc in inst.get("accounts", []):
            cv = cash_account_value(acc, month_idx)
            pv = cash_account_value(acc, pmi) if pmi is not None else None
            cash_acc_deltas[acc["id"]] = mom_change(cv, pv)

    inv_hold_deltas = {}
    for brk in investments:
        for h in brk.get("holdings", []):
            cv = inv_holding_value(h, month_idx)
            pv = inv_holding_value(h, pmi) if pmi is not None else None
            inv_hold_deltas[h["id"]] = mom_change(cv, pv)

    ast_item_deltas = {}
    for cat in assets:
        for item in cat.get("items", []):
            cv = ast_item_value(item, month_idx)
            pv = ast_item_value(item, pmi) if pmi is not None else None
            ast_item_deltas[item["id"]] = mom_change(cv, pv)

    return {
        "year":               year,
        "month_idx":          month_idx,
        "latest_month_idx":   latest_filled_month(cash, investments, assets),
        "summary":            summary,
        "cash_inst_totals":   cash_inst_totals,
        "cash_inst_deltas":   cash_inst_deltas,
        "inv_brk_totals":     inv_brk_totals,
        "inv_brk_deltas":     inv_brk_deltas,
        "ast_cat_totals":     ast_cat_totals,
        "ast_cat_deltas":     ast_cat_deltas,
        "cash_acc_deltas":    cash_acc_deltas,
        "inv_hold_deltas":    inv_hold_deltas,
        "ast_item_deltas":    ast_item_deltas,
        "net_worth_series":   net_worth_year_series(cash, investments, assets),
        "group_series": {
            "cash":        cash_year_series(cash),
            "investments": inv_year_series(investments),
            "assets":      ast_year_series(assets),
        },
    }


# ════════════════════════════════════════════════════════════════════
#  DASHBOARD SLICE
# ════════════════════════════════════════════════════════════════════

def compute_dashboard_networth(
        cash: list[dict], investments: list[dict], assets: list[dict]
) -> dict:
    """
    Net worth snapshot for the dashboard summary card.
    Uses the latest filled month.

    Returns:
        {
            "net_worth":         float,
            "total_cash":        float,
            "total_investments": float,
            "nw_mom_change":     float | None,
            "nw_mom_pct":        float | None,
            "net_worth_trend":   [float | None × 12],
            "allocation": { "cash": float, "investments": float, "assets": float },
        }
    """
    lfm  = latest_filled_month(cash, investments, assets)
    pmi  = _prev(lfm) if lfm is not None else None

    nw_cur  = net_worth_month_total(cash, investments, assets, lfm) if lfm is not None else 0.0
    nw_prev = net_worth_month_total(cash, investments, assets, pmi) if pmi is not None else None

    raw = net_worth_year_series(cash, investments, assets)
    trend = [v if v > 0.0 else None for v in raw]

    alloc = (
        allocation_at_month(cash, investments, assets, lfm)
        if lfm is not None
        else {"cash": {"amount": 0.0}, "investments": {"amount": 0.0}, "assets": {"amount": 0.0}}
    )

    return {
        "net_worth":         nw_cur,
        "total_cash":        alloc["cash"]["amount"],
        "total_investments": alloc["investments"]["amount"],
        "nw_mom_change":     mom_change(nw_cur, nw_prev),
        "nw_mom_pct":        mom_pct_change(nw_cur, nw_prev),
        "net_worth_trend":   trend,
        "allocation": {k: alloc[k]["amount"] for k in alloc},
    }