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

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

import uvicorn
import database.database as database
from routers import cashflow, networth, budget, dashboard

STATIC_DIR = Path(__file__).parent / "templates"

_PLACEHOLDER = (
    "<!doctype html><html><body style='font-family:sans-serif;padding:40px'>"
    "<h2>⛅ Coming soon</h2><p><a href='/'>← Dashboard</a></p></body></html>"
)


# ── Startup / shutdown ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="FinTrack", version="1.0", lifespan=lifespan)


# ── Page routes ───────────────────────────────────────────────────────────────

def _page(filename: str) -> FileResponse | HTMLResponse:
    path = STATIC_DIR / filename
    return FileResponse(path) if path.exists() else HTMLResponse(_PLACEHOLDER)


@app.get("/",         include_in_schema=False)
def page_dashboard(): return _page("dashboard.html")

@app.get("/cashflow", include_in_schema=False)
def page_cashflow():  return _page("cashflow.html")

@app.get("/networth", include_in_schema=False)
def page_networth():  return _page("networth.html")

@app.get("/budget",   include_in_schema=False)
def page_budget():    return _page("budget.html")

@app.get("/forecast", include_in_schema=False)
def page_forecast():  return _page("forecast.html")

@app.get("/chatbot",  include_in_schema=False)
def page_chatbot():   return _page("chatbot.html")


# ── API routers ───────────────────────────────────────────────────────────────

app.include_router(dashboard.router, prefix="/api/dashboard")
app.include_router(cashflow.router,  prefix="/api/cashflow")
app.include_router(networth.router,  prefix="/api/networth")
app.include_router(budget.router,    prefix="/api/budget")

if __name__ == "__main__":
    print("Link: " + "http://127.0.0.1:8000/")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
