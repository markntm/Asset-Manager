"""
routers/dashboard.py  —  GET /api/dashboard/summary

Combines compute_dashboard_networth and compute_dashboard_cashflow into a
single payload consumed by dashboard.html.  Also builds the flat accounts
table from the raw net-worth data.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from auth import current_user_id
from database import cashflow as cf_db
from database import networth as nw_db
from database import budget as bud_db
from calculations.cashflow import compute_dashboard_cashflow, expense_category_total, expense_month_total
from calculations.networth import (compute_dashboard_networth, latest_filled_month,
                                   net_worth_year_series, liab_year_series)

router = APIRouter(tags=["dashboard"])


def _v(values: dict, mi: int | None) -> float:
    """Read a monthly value from a str/int-keyed values dict."""
    if mi is None:
        return 0.0
    val = values.get(str(mi))
    if val is None:
        val = values.get(mi)
    return float(val) if val is not None else 0.0


def _build_accounts(nw_data: dict, lfm: int | None, nw_total: float) -> list[dict]:
    """
    Flatten all net-worth leaf nodes into dashboard table rows.

    Each row: {name, type, balance, pct_of_total, mom_change}.
    Entries with a zero balance at the latest filled month are excluded
    to keep the table clean.  Rows are sorted by balance descending.
    """
    if lfm is None:
        return []

    pmi = lfm - 1 if lfm > 0 else None
    rows: list[dict] = []

    for inst in nw_data["cash"]:
        for acc in inst.get("accounts", []):
            bal = _v(acc["values"], lfm)
            if bal == 0.0:
                continue
            prev = _v(acc["values"], pmi) if pmi is not None else None
            rows.append({
                "name":         f"{inst['name']} — {acc['name']}",
                "type":         "cash",
                "balance":      bal,
                "pct_of_total": round(bal / nw_total * 100, 2) if nw_total > 0 else None,
                "mom_change":   round(bal - prev, 2) if prev is not None else None,
            })

    for brk in nw_data["investments"]:
        for h in brk.get("holdings", []):
            bal = _v(h["values"], lfm)
            if bal == 0.0:
                continue
            prev = _v(h["values"], pmi) if pmi is not None else None
            rows.append({
                "name":         f"{brk['name']} — {h['ticker']}",
                "type":         "investment",
                "balance":      bal,
                "pct_of_total": round(bal / nw_total * 100, 2) if nw_total > 0 else None,
                "mom_change":   round(bal - prev, 2) if prev is not None else None,
            })

    for cat in nw_data["assets"]:
        for item in cat.get("items", []):
            bal = _v(item["values"], lfm)
            if bal == 0.0:
                continue
            prev = _v(item["values"], pmi) if pmi is not None else None
            rows.append({
                "name":         f"{cat['name']} — {item['name']}",
                "type":         "asset",
                "balance":      bal,
                "pct_of_total": round(bal / nw_total * 100, 2) if nw_total > 0 else None,
                "mom_change":   round(bal - prev, 2) if prev is not None else None,
            })

    for cat in nw_data["liabilities"]:
        for item in cat.get("items", []):
            bal = _v(item["values"], lfm)
            if bal == 0.0:
                continue
            prev = _v(item["values"], pmi) if pmi is not None else None
            rows.append({
                "name":         f"{cat['name']} — {item['name']}",
                "type":         "liability",
                "balance":      bal,
                "pct_of_total": round(bal / nw_total * 100, 2) if nw_total > 0 else None,
                "mom_change":   round(bal - prev, 2) if prev is not None else None,
            })

    rows.sort(key=lambda r: r["balance"], reverse=True)
    return rows


@router.get("/summary")
def get_dashboard_summary(
        year:  int | None = Query(None, ge=2000, le=2100),
        month: int | None = Query(None, ge=1, le=12),
        user_id: str = Depends(current_user_id)
):
    if year is None or month is None:   # fallback: Hawaii time (no DST)
        now = datetime.now(ZoneInfo("Pacific/Honolulu"))
        year, month = now.year, now.month
    current_month_idx = month - 1

    nw_data = nw_db.get_networth_data(user_id, year)
    cf_data = cf_db.get_cashflow_data(user_id, year)

    nw = compute_dashboard_networth(
        nw_data["cash"], nw_data["investments"], nw_data["assets"], nw_data["liabilities"]
    )
    cf = compute_dashboard_cashflow(
        cf_data["income"], cf_data["expenses"], current_month_idx
    )

    spend = [expense_month_total(cf_data["expenses"], mi) for mi in range(current_month_idx + 1)]
    recent = [v for v in spend if v > 0][-3:]
    avg_spend = sum(recent) / len(recent) if recent else None

    targets = {c["id"]: c["monthly_budget"] for c in bud_db.get_budget_categories(user_id) if c["monthly_budget"]}
    budget_total = sum(targets.values())
    spent_budgeted = sum(expense_category_total(c, current_month_idx)
                         for c in cf_data["expenses"] if c["id"] in targets)

    lfm      = latest_filled_month(nw_data["cash"], nw_data["investments"], nw_data["assets"], nw_data["liabilities"])
    accounts = _build_accounts(nw_data, lfm, nw["net_worth"] + nw["total_liabilities"])

    # Contiguous monthly series from first year with data through the current year
    first_year = min(nw_db.get_years(user_id), default=year)
    trend = []
    for y in range(min(first_year, year), year + 1):
        d = nw_data if y == year else nw_db.get_networth_data(user_id, y)
        nws  = net_worth_year_series(d["cash"], d["investments"], d["assets"], d["liabilities"])
        liab = liab_year_series(d["liabilities"])
        for mi in range(12):
            trend.append({"year": y, "month": mi, "value": nws[mi], "liabilities": liab[mi]})

    return {
        # Summary cards
        "net_worth":        nw["net_worth"],
        "cash":             nw["total_cash"],          # renamed from total_cash
        "investments":      nw["total_investments"],   # renamed from total_investments
        "monthly_cashflow": cf["monthly_cashflow"],
        "savings_rate":     cf["savings_rate"],
        "nw_mom_change":    nw["nw_mom_change"],
        "avg_monthly_spend": avg_spend,
        "runway_months":     nw["total_cash"] / avg_spend if avg_spend else None,
        "budget_total":      budget_total or None,
        "budget_remaining":  budget_total - spent_budgeted if budget_total else None,

        # Net Worth Trend line chart (12 months, None for unpopulated months)
        "net_worth_series": trend,

        # Allocation donut — frontend keys are savings/investments/assets
        "allocation": {
            "savings":     nw["allocation"]["cash"],
            "investments": nw["allocation"]["investments"],
            "assets":      nw["allocation"]["assets"],
            "liabilities": nw["allocation"]["liabilities"],
        },

        # Account overview table
        "accounts": accounts,
    }
