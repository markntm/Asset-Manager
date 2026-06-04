from __future__ import annotations

from typing import Optional


# ════════════════════════════════════════════════════════════════════
#  PRIVATE HELPERS
# ════════════════════════════════════════════════════════════════════

def _get(mapping: dict, month_idx: int) -> float:
    """
    Safely retrieve a month value from a dict whose keys may be stored
    as either str or int.  Uses an explicit None check — not `or` — so
    that a legitimately stored value of 0.0 is returned correctly.
    Returns 0.0 (not None) when the key is absent because absent == $0
    for arithmetic purposes; the frontend controls blank-vs-zero display.
    """
    val = mapping.get(str(month_idx))
    if val is None:
        val = mapping.get(month_idx)
    return float(val) if val is not None else 0.0


def _prev(month_idx: int) -> Optional[int]:
    """Previous month index, or None for January (no prior month in year)."""
    return month_idx - 1 if month_idx > 0 else None


# ════════════════════════════════════════════════════════════════════
#  INCOME
# ════════════════════════════════════════════════════════════════════

def income_category_value(row: dict, month_idx: int) -> float:
    """Single income category's stored value for one month."""
    return _get(row["values"], month_idx)


def income_month_total(income_rows: list[dict], month_idx: int) -> float:
    """Sum of all income category values for one month."""
    return sum(_get(r["values"], month_idx) for r in income_rows)


def income_year_total(income_rows: list[dict]) -> float:
    """Sum of all income across all 12 months."""
    return round(sum(income_month_total(income_rows, mi) for mi in range(12)), 2)


def income_monthly_series(income_rows: list[dict]) -> list[float]:
    """
    Ordered list of monthly income totals (index 0 = Jan … 11 = Dec).
    Consumed directly by the bar chart dataset in the year view.
    """
    return [round(income_month_total(income_rows, mi), 2) for mi in range(12)]


# ════════════════════════════════════════════════════════════════════
#  EXPENSES
# ════════════════════════════════════════════════════════════════════

def expense_subcategory_value(sub: dict, month_idx: int) -> float:
    """Single subcategory's stored value for one month."""
    return _get(sub["values"], month_idx)


def expense_category_total(cat: dict, month_idx: int) -> float:
    """
    Sum of all subcategory values within one expense category for one month.
    Expense categories are never directly editable — their total is always
    derived from their subcategories.
    """
    return sum(_get(sc["values"], month_idx) for sc in cat.get("subcategories", []))


def expense_month_total(expense_cats: list[dict], month_idx: int) -> float:
    """Sum across all expense categories for one month."""
    return sum(expense_category_total(c, month_idx) for c in expense_cats)


def expense_year_total(expense_cats: list[dict]) -> float:
    """Sum of all expenses across all 12 months."""
    return round(sum(expense_month_total(expense_cats, mi) for mi in range(12)), 2)


def expense_monthly_series(expense_cats: list[dict]) -> list[float]:
    """
    Ordered list of monthly expense totals (index 0 = Jan … 11 = Dec).
    Consumed directly by the bar chart dataset in the year view.
    """
    return [round(expense_month_total(expense_cats, mi), 2) for mi in range(12)]


def expense_category_year_totals(expense_cats: list[dict]) -> list[dict]:
    """
    Per-category totals summed across all 12 months.
    Used by the annual expense pie chart on the year summary view.

    Returns: [{ "id": str, "name": str, "total": float }, …]
    """
    return [
        {
            "id":    cat["id"],
            "name":  cat["name"],
            "total": round(
                sum(expense_category_total(cat, mi) for mi in range(12)), 2
            ),
        }
        for cat in expense_cats
    ]


# ════════════════════════════════════════════════════════════════════
#  BUDGETS
# ════════════════════════════════════════════════════════════════════

def budget_category_value(cat: dict, month_idx: int) -> float:
    """The user-entered monthly budget for a single expense category."""
    return _get(cat.get("budget", {}), month_idx)


def budget_month_total(expense_cats: list[dict], month_idx: int) -> float:
    """Sum of all category budgets for one month (shown in the expense block header)."""
    return round(
        sum(_get(c.get("budget", {}), month_idx) for c in expense_cats), 2
    )


# ════════════════════════════════════════════════════════════════════
#  NET FLOW  &  SAVINGS RATE
# ════════════════════════════════════════════════════════════════════

def net_cash_flow(income_total: float, expense_total: float) -> float:
    """Income minus expenses for any period."""
    return round(income_total - expense_total, 2)


def savings_rate(income_total: float, net_flow: float) -> Optional[float]:
    """
    Net flow as a percentage of income.
    Returns None — not 0 — when income is zero so the frontend can
    display "—" rather than a misleading 0 %.
    """
    if income_total <= 0:
        return None
    return round(net_flow / income_total * 100, 2)


# ════════════════════════════════════════════════════════════════════
#  DELTAS  (month-over-month change)
# ════════════════════════════════════════════════════════════════════

def month_delta(current: float, previous: Optional[float]) -> Optional[float]:
    """
    Signed difference between the current month and the previous month.
    Returns None for January (month_idx 0) or any month where there is
    no previous value to compare against — the frontend renders this as "—".
    """
    if previous is None:
        return None
    return round(current - previous, 2)


# ════════════════════════════════════════════════════════════════════
#  MONTH SUMMARY  ——  Pattern A response payload
#
#  Returned by every income-entry and expense-entry PUT endpoint so the
#  frontend never needs to recalculate locally.  The returned dict maps
#  field-for-field onto MonthSummaryOut in main.py.
# ════════════════════════════════════════════════════════════════════

def compute_month_summary(
        income_rows:  list[dict],
        expense_cats: list[dict],
        month_idx:    int,
) -> dict:
    """
    Compute every number visible in the cashflow month view for the
    given month index.

    The caller (main.py endpoint) is responsible for passing income_rows
    and expense_cats that are already scoped to the correct year.

    Returns a plain dict that Pydantic coerces into MonthSummaryOut.
    """
    pmi = _prev(month_idx)

    # ── Block-level totals ────────────────────────────────────────
    inc_total = income_month_total(income_rows,   month_idx)
    exp_total = expense_month_total(expense_cats, month_idx)
    bud_total = budget_month_total(expense_cats,  month_idx)
    net       = net_cash_flow(inc_total, exp_total)
    rate      = savings_rate(inc_total, net)

    # ── Block-level deltas ────────────────────────────────────────
    inc_prev  = income_month_total(income_rows,   pmi) if pmi is not None else None
    exp_prev  = expense_month_total(expense_cats, pmi) if pmi is not None else None
    inc_delta = month_delta(inc_total, inc_prev)
    exp_delta = month_delta(exp_total, exp_prev)

    # ── Per income-category breakdown ─────────────────────────────
    income_cat_summaries = [
        {
            "id":    row["id"],
            "value": income_category_value(row, month_idx),
            "delta": month_delta(
                income_category_value(row, month_idx),
                income_category_value(row, pmi) if pmi is not None else None,
            ),
        }
        for row in income_rows
    ]

    # ── Per expense-category + subcategory breakdown ──────────────
    expense_cat_summaries = []
    for cat in expense_cats:
        cat_total = expense_category_total(cat, month_idx)
        cat_prev  = expense_category_total(cat, pmi) if pmi is not None else None

        sub_summaries = [
            {
                "id":    sc["id"],
                "value": expense_subcategory_value(sc, month_idx),
                "delta": month_delta(
                    expense_subcategory_value(sc, month_idx),
                    expense_subcategory_value(sc, pmi) if pmi is not None else None,
                ),
            }
            for sc in cat.get("subcategories", [])
        ]

        expense_cat_summaries.append({
            "id":            cat["id"],
            "total":         cat_total,
            "budget":        budget_category_value(cat, month_idx),
            "delta":         month_delta(cat_total, cat_prev),
            "subcategories": sub_summaries,
        })

    return {
        "month_idx":          month_idx,
        "income_total":       inc_total,
        "income_delta":       inc_delta,
        "expense_total":      exp_total,
        "expense_delta":      exp_delta,
        "budget_total":       bud_total,
        "net_cash_flow":      net,
        "savings_rate":       rate,
        "income_categories":  income_cat_summaries,
        "expense_categories": expense_cat_summaries,
    }


# ════════════════════════════════════════════════════════════════════
#  YEAR SUMMARY
#  Supplies the year-view summary cards and both chart datasets.
# ════════════════════════════════════════════════════════════════════

def compute_year_summary(
        income_rows:  list[dict],
        expense_cats: list[dict],
        year:         int,
) -> dict:
    """
    Aggregated annual figures plus the per-month series arrays consumed
    directly by Chart.js on the year view (bar chart + annual pie chart).
    """
    inc_series = income_monthly_series(income_rows)
    exp_series = expense_monthly_series(expense_cats)
    net_series = [round(i - e, 2) for i, e in zip(inc_series, exp_series)]

    inc_total = round(sum(inc_series), 2)
    exp_total = round(sum(exp_series), 2)
    net_total = round(inc_total - exp_total, 2)
    rate      = savings_rate(inc_total, net_total)

    return {
        "year":                   year,
        "income_total":           inc_total,
        "expense_total":          exp_total,
        "net_total":              net_total,
        "savings_rate":           rate,
        "income_monthly_series":  inc_series,
        "expense_monthly_series": exp_series,
        "net_monthly_series":     net_series,
        "category_year_totals":   expense_category_year_totals(expense_cats),
    }


# ════════════════════════════════════════════════════════════════════
#  DASHBOARD SLICE
#  Called from db.get_dashboard_summary() to contribute the cashflow
#  numbers shown on the dashboard page without re-implementing logic.
# ════════════════════════════════════════════════════════════════════

def compute_dashboard_cashflow(
        income_rows:       list[dict],
        expense_cats:      list[dict],
        current_month_idx: int,
) -> dict:
    """
    Locate the most recently populated month at or before current_month_idx
    and return its cashflow figures for the dashboard summary card.

    Walks backwards so months with no data are skipped gracefully.

    Returns:
        monthly_cashflow  – net cash flow for the active month
        savings_rate      – as a percentage, or None if no income
        active_month      – the month index used, or None if no data exists
    """
    active_mi = None
    for mi in range(current_month_idx, -1, -1):
        if (income_month_total(income_rows, mi) > 0
                or expense_month_total(expense_cats, mi) > 0):
            active_mi = mi
            break

    if active_mi is None:
        return {"monthly_cashflow": 0.0, "savings_rate": None, "active_month": None}

    inc  = income_month_total(income_rows,   active_mi)
    exp  = expense_month_total(expense_cats, active_mi)
    net  = net_cash_flow(inc, exp)
    rate = savings_rate(inc, net)

    return {
        "monthly_cashflow": round(net,  2),
        "savings_rate":     rate,
        "active_month":     active_mi,
    }