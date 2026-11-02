"""
main.py  —  FinTrack FastAPI application.

Run with:
    uvicorn main:app --reload --port 8000

HTML pages are served from ./static/.  The four existing pages
(dashboard, cashflow, networth, budget) must be placed there as:
    static/dashboard.html
    static/cashflow.html
    static/networth.html
    static/budget.html

Any page file that doesn't exist yet returns a simple placeholder.
"""

from __future__ import annotations

import os, uvicorn
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from database.base import NotFound
from routers import cashflow, networth, budget, dashboard, account, transactions, statements

STATIC_DIR = Path(__file__).parent / "templates"

_PLACEHOLDER = (
    "<!doctype html><html><body style='font-family:sans-serif;padding:40px'>"
    "<h2>⛅ Coming soon</h2><p><a href='/'>← Dashboard</a></p></body></html>"
)

app = FastAPI(title="FinTrack", version="1.0")

@app.exception_handler(NotFound)
async def _not_found(request, exc):
    return JSONResponse({"detail": "Not found"}, status_code=404)


app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SECRET_KEY"],
    https_only=bool(os.environ.get("VERCEL")),   # Secure cookies on Vercel only (plain http locally)
    same_site="lax",
    max_age=14 * 24 * 3600, # Consider adding "remember-me" checkbox to login
)


# ── Page routes ───────────────────────────────────────────────────────────────

def _page(request: Request, filename: str):
    if not request.session.get("uid"):
        return RedirectResponse("/login", status_code=303)
    path = STATIC_DIR / filename
    return FileResponse(path) if path.exists() else HTMLResponse(_PLACEHOLDER)


def _public_page(request: Request):
    if request.session.get("uid"):
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/",              include_in_schema=False)
def page_dashboard(request: Request):
    return _page(request, "dashboard.html")

@app.get("/cashflow",      include_in_schema=False)
def page_cashflow(request: Request):
    return _page(request, "cashflow.html")

@app.get("/networth",      include_in_schema=False)
def page_networth(request: Request):
    return _page(request, "networth.html")

@app.get("/transactions",  include_in_schema=False)
def page_transactions(request: Request):
    return _page(request, "transactions.html")

@app.get("/statements",    include_in_schema=False)
def page_statements(request: Request):
    return _page(request, "statementUpload.html")

@app.get("/budget",        include_in_schema=False)
def page_budget(request: Request):
    return _page(request, "budget.html")

@app.get("/forecast",      include_in_schema=False)
def page_forecast(request: Request):
    return _page(request, "forecast.html")

@app.get("/chatbot",       include_in_schema=False)
def page_chatbot(request: Request):
    return _page(request, "chatbot.html")

@app.get("/login",         include_in_schema=False)
def page_login(request: Request):
    return _public_page(request)

@app.get("/signup",        include_in_schema=False)
def page_signup(request: Request):
    return _public_page(request)

@app.get("/logout",        include_in_schema=False)
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/responsive.css", include_in_schema=False)
def responsive_css():
    return FileResponse(STATIC_DIR / "responsive.css", media_type="text/css")


# ── API routers ───────────────────────────────────────────────────────────────

app.include_router(dashboard.router,    prefix="/api/dashboard")
app.include_router(cashflow.router,     prefix="/api/cashflow")
app.include_router(networth.router,     prefix="/api/networth")
app.include_router(transactions.router, prefix="/api/transactions")
app.include_router(statements.router,   prefix="/api/statements")
app.include_router(budget.router,       prefix="/api/budget")
app.include_router(account.router,      prefix="/api/auth")

if __name__ == "__main__":
    print("Link: " + "http://127.0.0.1:8000/")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
