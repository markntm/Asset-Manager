"""
calculations/statements.py  —  Statement parsing (CSV + text-based PDF). Bytes in, dict out.
No DB, no FastAPI.  Anything the parser isn't sure of is left None so the UI labels it "missing".

Sign convention everywhere:  amount < 0 = money out,  amount > 0 = money in.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Optional


class StatementError(ValueError):
    """User-facing parse failure."""


# ════════════════════════════════════════════════════════════════════
#  MONEY / DATES
# ════════════════════════════════════════════════════════════════════

def _amt_re(num: str):
    return re.compile(rf"^(\(?)\s*([-+]?)\s*\$?\s*([-+]?)({num})\)?\s*(CR|DR)?\s*(-?)$", re.I)

_AMT_LOOSE, _AMT_STRICT = _amt_re(r"\d[\d,]*(?:\.\d+)?"), _amt_re(r"\d[\d,]*\.\d{2}")


def to_amount(s, strict: bool = False):
    """'(12.30)', '- $25.00', '12.30-', '12.30 CR' → (signed float, 'CR'|'DR'|None); (None, None) if not money."""
    t = str(s or "").strip().replace("\u2212", "-").replace("\u2013", "-")
    m = (_AMT_STRICT if strict else _AMT_LOOSE).match(t)
    if not m:
        return None, None
    paren, s1, s2, num, tag, trail = m.groups()
    v = float(num.replace(",", ""))
    if paren or "-" in (s1, s2, trail):
        v = -v
    return v, (tag.upper() if tag else None)


def _is_money(text: str) -> bool:
    return to_amount(text, strict=True)[0] is not None


_DATE_FMTS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y/%m/%d",
              "%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y", "%d-%b-%Y", "%d %b %Y")


def to_date(s) -> Optional[date]:
    t = re.split(r"[T ]\d{1,2}:\d{2}", str(s or "").strip(), maxsplit=1)[0]   # drop time-of-day
    t = re.sub(r"\.(?=\s)", "", t).strip()                                    # "Oct. 3" → "Oct 3"
    for f in _DATE_FMTS:
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            pass
    return None


def _iso(d) -> Optional[str]:
    return d.isoformat() if d else None


# ════════════════════════════════════════════════════════════════════
#  SIGN CONVENTIONS + CHECKSUM
# ════════════════════════════════════════════════════════════════════

_IN_KW = {
    "credit": r"payment|thank you|autopay|refund|reversal|statement credit",
    "other":  r"deposit|payroll|direct dep|salary|refund|interest paid|cashback|payment[ -]+thank you",
}
_OUT_KW = {
    "credit": None,
    "other":  r"purchase|\bpos\b|withdrawal|\batm\b|debit card|check ?card|bill pay|zelle to|\bsale\b",
}


def decide_flip(rows: list[dict], stype: str) -> tuple[bool, str]:
    """
    Sign-ambiguous rows (single Amount column, no CR/DR tag) can use either convention:
      banks:  debits negative            →  keep
      cards:  purchases positive (Amex…) →  flip
    Vote using descriptions whose direction we know; fall back to row majority for cards.
    """
    amb = [r for r in rows if r["amb"] and r["raw"]]
    if not amb:
        return False, "Debit/credit columns or CR/DR tags found — no sign guess needed."
    key = "credit" if stype == "credit" else "other"
    inn = re.compile(_IN_KW[key], re.I)
    out = re.compile(_OUT_KW[key], re.I) if _OUT_KW[key] else None
    sgn = lambda r: 1 if r["raw"] > 0 else -1
    votes = sum(sgn(r) for r in amb if inn.search(r["merchant"]))
    if out:
        votes -= sum(sgn(r) for r in amb if out.search(r["merchant"]))
    if votes > 0:
        return False, "Inflow-looking rows (deposits/payments) are positive in the file — kept as is."
    if votes < 0:
        return True, "Inflow-looking rows are negative in the file — signs were flipped."
    if stype == "credit" and sum(1 for r in amb if r["raw"] > 0) > len(amb) / 2:
        return True, "Most rows are positive on a credit card (purchases) — signs were flipped."
    return False, "No clear signal — kept the file's signs. Use “Invert all signs” if they look backwards."


def checksum(stype: str, opening, closing, amounts) -> dict:
    """
    opening + Σ(amounts) == closing   (checking/savings/venmo: balance = money you have)
    opening − Σ(amounts) == closing   (credit card: balance = money you owe, as printed)
    """
    total = round(sum(a for a in amounts if a is not None), 2)
    if opening is None or closing is None:
        return {"status": "unverified", "txn_total": total, "expected_closing": None, "diff": None}
    expected = round(opening + (-1 if stype == "credit" else 1) * total, 2)
    diff = round(closing - expected, 2)
    return {"status": "ok" if abs(diff) < 0.005 else "mismatch",
            "txn_total": total, "expected_closing": expected, "diff": diff}


# ════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ════════════════════════════════════════════════════════════════════

_XFER = re.compile(r"\b(transfer|xfer|autopay|payment[ -]+thank you|online payment|credit card payment|card payment)\b", re.I)


def guess_type(text: str, filename: str = "") -> str:
    t = f"{filename} {text}".lower()
    if "venmo" in t:
        return "venmo"
    if re.search(r"credit card|american express|\bamex\b|discover|minimum payment|credit limit|new balance|payment due|payment[ -]+thank you", t):
        return "credit"
    return "savings" if "savings" in t else "checking"


def guess_bank(banks, head: str) -> Optional[str]:
    h = head.lower()
    for b in sorted(banks, key=lambda b: -len(b["name"])):
        if b["name"].lower() in h:
            return b["id"]
    return None


def merchant_key(m: str) -> str:
    """Stable key for remembering a merchant's category (first 3 letter-words)."""
    return " ".join(re.sub(r"[^a-z ]+", " ", m.lower()).split()[:3])


def _derive_balances(rows, bal_sign: int):
    """Opening/closing from a running-balance column (rows in file order, amounts already signed)."""
    wb = [r for r in rows if r.get("bal") is not None and r["amount"] is not None]
    if not wb:
        return None, None
    dated = [r["date"] for r in rows if r["date"]]
    desc = len(dated) > 1 and dated[0] > dated[-1]               # newest-first file
    oldest, newest = (wb[-1], wb[0]) if desc else (wb[0], wb[-1])
    return round(oldest["bal"] - bal_sign * oldest["amount"], 2), newest["bal"]


def _finish(fmt, rows, stype, banks, head, opening, closing, period=(None, None), extra=None) -> dict:
    flipped, reason = decide_flip(rows, stype)
    for r in rows:
        r["amount"] = None if r["raw"] is None else (-r["raw"] if flipped and r["amb"] else r["raw"])

    source = "statement" if (opening is not None or closing is not None) else None
    if opening is None and closing is None:
        opening, closing = _derive_balances(rows, -1 if stype == "credit" else 1)
        source = "running_balance" if opening is not None else None

    dates = [r["date"] for r in rows if r["date"]]
    ps, pe = period[0] or (min(dates) if dates else None), period[1] or (max(dates) if dates else None)

    out = [{"date": _iso(r["date"]), "merchant": r["merchant"], "amount": r["amount"],
            "category": None, "is_transfer": bool(_XFER.search(r["merchant"]))} for r in rows]
    warnings = []
    if not out:
        warnings.append("No transactions were detected automatically. Add rows manually below, or try a CSV export.")
    if any(r["date"] is None for r in out):
        warnings.append("Some rows have no readable date — fill them in or remove them.")
    if opening is None or closing is None:
        warnings.append("Opening and/or closing balance not found — the checksum can't verify this statement until you enter them.")
    elif source == "running_balance":
        warnings.append("Opening/closing balance were derived from the running-balance column (partial check).")

    return {
        "format": fmt, "rows": out,
        "meta": {"bank_id": guess_bank(banks, head), "account_id": None, "statement_type": stype,
                 "period_start": _iso(ps), "period_end": _iso(pe),
                 "opening_balance": opening, "closing_balance": closing, "balance_source": source},
        "sign": {"flipped": flipped, "reason": reason},
        "checksum": checksum(stype, opening, closing, [r["amount"] for r in out]),
        "warnings": warnings, **(extra or {}),
    }


# ════════════════════════════════════════════════════════════════════
#  CSV
# ════════════════════════════════════════════════════════════════════

_ROLES = {   # role → header regexes, best match first
    "date":     [r"^transaction date$", r"^trans\.? date$", r"^date$", r"^posting date$", r"^post(ed)? date$",
                 r"^date posted$", r"^posted$", r"^datetime$", r"date"],
    "merchant": [r"^description$", r"^merchant", r"^payee$", r"^name$", r"^original description$",
                 r"^details?$", r"^memo$", r"^note$", r"^narrative$", r"description|payee|merchant"],
    "amount":   [r"^amount$", r"^amount \(total\)$", r"^transaction amount$", r"^amt$", r"amount"],
    "debit":    [r"^debits?( amount)?$", r"^withdrawals?( amount)?$", r"^money out$", r"^paid out$"],
    "credit":   [r"^credits?( amount)?$", r"^deposits?( amount)?$", r"^money in$", r"^paid in$"],
    "type":     [r"^(transaction )?type$", r"^dr/?cr$", r"^debit/credit$", r"^credit/debit$"],
    "balance":  [r"^(running )?balance$"],
    "status":   [r"^status$"],
    "from":     [r"^from$"],
    "to":       [r"^to$"],
}
_BAD_STATUS = re.compile(r"pending|cancel|fail|declin|reject|expired", re.I)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", "replace")


def _detect_roles(headers) -> dict:
    low = [re.sub(r"\s+", " ", h.strip().lower()) for h in headers]
    found, used = {}, set()
    for role, pats in _ROLES.items():
        for p in pats:
            idx = next((i for i, h in enumerate(low) if i not in used and re.search(p, h)), None)
            if idx is not None:
                found[role] = idx
                used.add(idx)
                break
    return found


def _find_header(grid):
    """Banks/Venmo put account info above the real header row — scan for it."""
    for i, row in enumerate(grid[:30]):
        roles = _detect_roles(row)
        if "date" in roles and ("amount" in roles or "debit" in roles or "credit" in roles):
            return i, roles
    i = next((i for i, r in enumerate(grid[:30]) if sum(1 for c in r if c) >= 3), 0)
    return i, _detect_roles(grid[i])


def parse_csv(data: bytes, filename: str = "", banks=(), mapping: Optional[dict] = None,
              statement_type: Optional[str] = None) -> dict:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    grid = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]
    grid = [r for r in grid if any(r)]
    if not grid:
        raise StatementError("The file is empty.")

    hi, colmap = _find_header(grid)
    headers = grid[hi]
    for role, name in (mapping or {}).items():             # user overrides from the UI
        if name and name in headers:
            colmap[role] = headers.index(name)
        else:
            colmap.pop(role, None)

    low = [h.lower() for h in headers]
    bb = low.index("beginning balance") if "beginning balance" in low else None   # Venmo
    eb = low.index("ending balance") if "ending balance" in low else None

    use_type = False                                        # a Type column that is purely Debit/Credit
    if "type" in colmap and "amount" in colmap:
        vals = {r[colmap["type"]].lower() for r in grid[hi + 1:] if colmap["type"] < len(r) and r[colmap["type"]]}
        use_type = bool(vals) and vals <= {"debit", "credit", "dr", "cr", "d", "c"}

    rows, opening, closing = [], None, None
    for r in grid[hi + 1:]:
        cell = lambda role: r[colmap[role]] if role in colmap and colmap[role] < len(r) else ""
        if bb is not None and bb < len(r) and r[bb] and opening is None:
            opening = to_amount(r[bb])[0]
        if eb is not None and eb < len(r) and r[eb]:
            closing = to_amount(r[eb])[0] if to_amount(r[eb])[0] is not None else closing
        if _BAD_STATUS.search(cell("status")):
            continue

        d = to_date(cell("date"))
        merchant = re.sub(r"\s+", " ", cell("merchant")).strip()
        raw, amb, tag = None, True, None
        if "amount" in colmap:
            raw, tag = to_amount(cell("amount"))
            if raw is not None and use_type:                # explicit Debit/Credit label
                raw, amb = (abs(raw) if cell("type").lower() in ("credit", "cr", "c") else -abs(raw)), False
        elif "debit" in colmap or "credit" in colmap:       # separate columns: unambiguous
            dv, cv = to_amount(cell("debit"))[0], to_amount(cell("credit"))[0]
            if dv is not None or cv is not None:
                raw, amb = abs(cv or 0) - abs(dv or 0), False
        if raw is not None and tag:                         # "12.30 CR" / "DR"
            raw, amb = (abs(raw) if tag == "CR" else -abs(raw)), False
        if "to" in colmap and "from" in colmap and raw is not None:     # Venmo: show the other party
            who = cell("to") if raw < 0 else cell("from")
            merchant = f"{who} — {merchant}" if who and merchant else (who or merchant)
        merchant = merchant or cell("type")

        if (d is None and raw is None) or (raw is None and not merchant):
            continue                                        # headers/footers/summary rows
        rows.append({"date": d, "merchant": merchant[:200], "raw": raw, "amb": amb,
                     "bal": to_amount(cell("balance"))[0]})

    stype = statement_type or guess_type(text[:4000], filename)
    names = {role: headers[i] for role, i in colmap.items() if i < len(headers)}
    out = _finish("csv", rows, stype, banks, f"{filename} {text[:3000]}", opening, closing,
                  extra={"csv": {"headers": headers, "mapping": names}})
    if "date" not in colmap or not ({"amount", "debit", "credit"} & colmap.keys()):
        out["warnings"].insert(0, "Couldn't identify the date and/or amount columns — pick them in “CSV columns”.")
    return out


# ════════════════════════════════════════════════════════════════════
#  PDF  (text-based statements; scans need OCR — later feature)
# ════════════════════════════════════════════════════════════════════

_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_COL_WORDS = {
    "debit":   {"withdrawals", "withdrawal", "debits", "debit", "charges"},
    "credit":  {"deposits", "deposit", "credits", "credit", "additions"},
    "amount":  {"amount"},
    "balance": {"balance"},
}
_SKIP_LINE = re.compile(r"\b(beginning|opening|ending|closing|previous|new|statement) balance\b|balance forward"
                        r"|^total (for|this|deposits|withdrawals|fees|interest|purchases|payments|credits|debits|charges)", re.I)

_D = r"(\d{1,2}/\d{1,2}/\d{2,4}|[A-Za-z]{3,9}\.? \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2})"
_RANGE = re.compile(rf"{_D}\s*(?:to|through|thru|–|—|-)\s*{_D}", re.I)
_AMT_S = r"(\(?-?\$?\s*-?\d[\d,]*\.\d{2}\)?-?)"
_OPEN = re.compile(r"(?:previous|beginning|opening|starting)\s+balance[^\n]{0,40}?" + _AMT_S, re.I)
_CLOSE = re.compile(r"(?:ending|closing|new|statement)\s+balance[^\n]{0,40}?" + _AMT_S, re.I)


def _group_lines(words) -> list[list[dict]]:
    lines = []
    for w in sorted(words, key=lambda w: w["top"]):
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= 3:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(l, key=lambda w: w["x0"]) for l in lines]


def _merge_tokens(line):
    """Glue '$' / '-' onto the number beside it and 'CR'/'DR' onto the preceding amount."""
    out, i = [], 0
    while i < len(line):
        w, t = dict(line[i]), line[i]["text"]
        nxt = line[i + 1] if i + 1 < len(line) else None
        if t in ("$", "-", "+", "-$", "+$", "($") and nxt and nxt["x0"] - w["x1"] < 4:
            w["text"], w["x1"] = t + nxt["text"], nxt["x1"]
            i += 1
        elif t.upper() in ("CR", "DR") and out and _is_money(out[-1]["text"]):
            out[-1]["text"] += t.upper()
            out[-1]["x1"] = w["x1"]
            i += 1
            continue
        out.append(w)
        i += 1
    return out


def _header_cols(toks):
    """Column header line → {role: (x0, x1)}; None if this isn't a header."""
    if any(_is_money(t["text"]) for t in toks):
        return None
    texts = [re.sub(r"[^a-z/]", "", t["text"].lower()) for t in toks]
    cols = {}
    for role, words in _COL_WORDS.items():
        hit = [t for t, x in zip(toks, texts) if x in words]
        if hit:
            cols[role] = (min(t["x0"] for t in hit), max(t["x1"] for t in hit))
    anchors = {"date", "description", "transaction", "details"} & set(texts)
    return cols if cols and (len(cols) >= 2 or anchors) else None


def _nearest(cols, tok, roles):
    def dist(span):
        return min(abs(tok["x1"] - span[1]), abs((tok["x0"] + tok["x1"]) / 2 - (span[0] + span[1]) / 2))
    cand = [(dist(cols[r]), r) for r in roles if r in cols]
    return min(cand)[1] if cand else None


def _take_date(toks):
    """Leading date → ((month, day, year|None), words used); else (None, 0)."""
    if not toks:
        return None, 0
    t0 = toks[0]["text"]
    if m := re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", t0):
        yr = int(m[3]) + (2000 if int(m[3]) < 100 else 0) if m[3] else None
        return (int(m[1]), int(m[2]), yr), 1
    if m := re.match(r"^(\d{4})-(\d{2})-(\d{2})$", t0):
        return (int(m[2]), int(m[3]), int(m[1])), 1
    m = re.match(r"^([A-Za-z]{3})[a-z]*\.?$", t0)
    if m and m[1].lower() in _MONTHS and len(toks) > 1 and re.match(r"^\d{1,2},?$", toks[1]["text"]):
        n, yr = 2, None
        if len(toks) > 2 and re.match(r"^\d{4}$", toks[2]["text"]):
            yr, n = int(toks[2]["text"]), 3
        return (_MONTHS[m[1].lower()], int(toks[1]["text"].rstrip(",")), yr), n
    return None, 0


def _resolve(parts, ref: date) -> Optional[date]:
    """Dates without a year take the statement's year (Dec rows on a January statement → previous year)."""
    mo, dy, yr = parts
    try:
        if yr:
            return date(yr, mo, dy)
        d = date(ref.year, mo, dy)
        return date(ref.year - 1, mo, dy) if (d - ref).days > 45 else d
    except ValueError:
        return None


def _pdf_rows(lines, ref: date) -> list[dict]:
    rows, cols = [], {}
    for line in lines:
        toks = _merge_tokens(line)
        if hdr := _header_cols(toks):
            cols = hdr
            continue
        parts, n = _take_date(toks)
        if not parts:
            continue
        rest = toks[n:]
        rest = rest[_take_date(rest)[1]:]                   # skip a second (posting) date
        k = len(rest)
        while k > 0 and _is_money(rest[k - 1]["text"]):
            k -= 1
        desc, money = rest[:k], rest[k:]
        merchant = re.sub(r"\s+", " ", " ".join(t["text"] for t in desc)).strip()
        if not money or not merchant or _SKIP_LINE.search(merchant):
            continue

        vals = [(to_amount(t["text"], strict=True), t) for t in money]
        raw = bal = tag = None
        amb = True
        if "debit" in cols or "credit" in cols:             # position decides debit vs credit
            dv = cv = None
            for (v, tg), t in vals:
                role = _nearest(cols, t, ("debit", "credit", "balance", "amount"))
                if role == "debit":    dv = abs(v)
                elif role == "credit": cv = abs(v)
                elif role == "balance": bal = v
                elif role == "amount": raw, tag = v, tg
            if dv is not None or cv is not None:
                raw, amb = (cv or 0) - (dv or 0), False
        elif "amount" in cols:
            for (v, tg), t in vals:
                if _nearest(cols, t, ("amount", "balance")) == "balance":
                    bal = v
                else:
                    raw, tag = v, tg
        else:                                               # no headers: [amount] or [amount, balance]
            raw, tag = vals[0][0]
            if len(vals) > 1:
                bal = vals[-1][0][0]
        if raw is not None and tag:
            raw, amb = (abs(raw) if tag == "CR" else -abs(raw)), False
        if raw is None:
            continue
        rows.append({"date": _resolve(parts, ref), "merchant": merchant[:200], "raw": raw, "amb": amb, "bal": bal})
    return rows


def parse_pdf(data: bytes, filename: str = "", banks=(), statement_type: Optional[str] = None) -> dict:
    try:
        import pdfplumber
    except ImportError as exc:
        raise StatementError("PDF support needs `pip install pdfplumber`.") from exc
    try:
        pages = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                pages.append((page.extract_text() or "", _group_lines(page.extract_words(x_tolerance=1.5, y_tolerance=2))))
    except Exception as exc:
        raise StatementError("Couldn't read this PDF (corrupt or password-protected).") from exc

    full = "\n".join(t for t, _ in pages)
    if not full.strip():
        raise StatementError("This PDF has no selectable text (it's a scan). OCR is a later feature — try the bank's CSV export.")

    m = _RANGE.search(full)
    ps, pe = (to_date(m[1]), to_date(m[2])) if m else (None, None)
    if not (ps and pe and ps <= pe):
        ps = pe = None
    o, c = _OPEN.search(full), _CLOSE.search(full)
    opening = to_amount(o[1])[0] if o else None
    closing = to_amount(c[1])[0] if c else None

    rows = _pdf_rows([l for _, ls in pages for l in ls], pe or date.today())
    out = _finish("pdf", rows, statement_type or guess_type(full, filename), banks,
                  f"{filename} {full[:3000]}", opening, closing, (ps, pe))
    if not pe:
        out["warnings"].append("Statement period not found — dates without a year assume the current year.")
    return out
