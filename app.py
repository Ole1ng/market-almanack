"""Market Almanack — local offline market dashboard.

Run:  python app.py     then open http://localhost:8000

FastAPI serves a single-page dashboard plus a small JSON API. All data is
persisted to SQLite so the last session renders immediately on reload. Nothing
auto-refreshes; updates are triggered by the three buttons in the UI.
"""

from __future__ import annotations

import re
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import analysis
import earnings
import news
import screeners
import store
from panels import spy_positioning, ticker_positioning

BASE = Path(__file__).parent
STATIC = BASE / "static"

app = FastAPI(title="Market Almanack")


def _ensure_nltk() -> None:
    """Auto-download NLTK stopwords on first run so the user need not."""
    try:
        import nltk
        from nltk.corpus import stopwords

        try:
            stopwords.words("english")
        except LookupError:
            nltk.download("stopwords", quiet=True)
    except Exception as exc:  # pragma: no cover - non-fatal, analysis falls back
        print(f"[startup] NLTK stopwords unavailable ({exc}); using fallback list")


@app.on_event("startup")
def _startup() -> None:
    store.init_db()
    _ensure_nltk()


# --------------------------------------------------------------------------- #
# Static + index
# --------------------------------------------------------------------------- #

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

@app.get("/api/state")
def api_state() -> JSONResponse:
    """Full last-known state for initial render."""
    return JSONResponse(store.get_all())


def _refresh_earnings(out: dict) -> None:
    """Fetch earnings + store; mutate `out` with the resulting record."""
    try:
        payload = earnings.fetch_earnings()
        status = "ok" if payload["rows"] else "empty"
        out["earnings"] = store.save_panel("earnings", payload, status=status)
    except Exception as exc:
        store.update_status("earnings", "error", str(exc))
        out["earnings"] = store.get_panel("earnings")


@app.post("/api/refresh/screeners")
def api_refresh_screeners() -> JSONResponse:
    """Re-run both screeners (panels 1-2). Stale data is kept on failure.

    The earnings watchlist is partly derived from screener output, so when
    EARNINGS_REFRESH_WITH_SCREENERS is set we refresh earnings here too,
    keeping the two in sync.
    """
    out = {}
    for key, fn in (("screener_day", screeners.run_daytrading),
                    ("screener_swing", screeners.run_swing)):
        try:
            payload = fn()
            status = "ok" if payload["rows"] else "empty"
            out[key] = store.save_panel(key, payload, status=status)
        except Exception as exc:
            store.update_status(key, "error", str(exc))
            out[key] = store.get_panel(key)

    if earnings.EARNINGS_REFRESH_WITH_SCREENERS:
        _refresh_earnings(out)
    return JSONResponse(out)


@app.post("/api/refresh/earnings")
def api_refresh_earnings() -> JSONResponse:
    """Re-fetch upcoming earnings for the watchlist. Stale data kept on failure."""
    out = {}
    _refresh_earnings(out)
    return JSONResponse(out)


@app.post("/api/refresh/news")
def api_refresh_news() -> JSONResponse:
    """Re-fetch all news feeds (panels 3-7). Stale data is kept on failure."""
    out = {}
    for key in ("news_us", "news_global", "news_energy",
                "news_precious", "news_commodities"):
        try:
            items = news.fetch_panel(key)
            status = "ok" if items else "empty"
            out[key] = store.save_panel(key, items, status=status)
        except Exception as exc:
            store.update_status(key, "error", str(exc))
            out[key] = store.get_panel(key)
    return JSONResponse(out)


@app.post("/api/refresh/analysis")
def api_refresh_analysis() -> JSONResponse:
    """Regenerate analyses (panels 8-9) from currently cached news."""
    def cached(key: str) -> list[dict]:
        rec = store.get_panel(key)
        return (rec or {}).get("payload") or []

    out = {}
    try:
        macro = analysis.build_macro(cached("news_us"), cached("news_global"))
        out["analysis_macro"] = store.save_panel(
            "analysis_macro", macro,
            status="empty" if macro["empty"] else "ok")
    except Exception as exc:
        store.update_status("analysis_macro", "error", str(exc))
        out["analysis_macro"] = store.get_panel("analysis_macro")

    try:
        commodity = analysis.build_commodity(
            cached("news_energy"), cached("news_precious"),
            cached("news_commodities"))
        out["analysis_commodity"] = store.save_panel(
            "analysis_commodity", commodity,
            status="empty" if commodity["empty"] else "ok")
    except Exception as exc:
        store.update_status("analysis_commodity", "error", str(exc))
        out["analysis_commodity"] = store.get_panel("analysis_commodity")

    return JSONResponse(out)


@app.post("/api/refresh/spy_positioning")
def api_refresh_spy_positioning() -> JSONResponse:
    """Fetch the CBOE SPY chain, compute the positioning snapshot, persist it.

    Heavy (full chain fetch + zero-gamma spot ladder) so it has its own button,
    uncoupled from news/screeners. On failure the cached snapshot is kept behind
    an error badge, exactly like the other panels.
    """
    out = {}
    try:
        payload = spy_positioning.refresh()
        out["spy_positioning"] = store.save_panel("spy_positioning", payload, status="ok")
    except Exception as exc:
        store.update_status("spy_positioning", "error", str(exc))
        out["spy_positioning"] = store.get_panel("spy_positioning")
    return JSONResponse(out)


@app.post("/api/refresh/ticker_positioning")
def api_refresh_ticker_positioning(symbol: str) -> JSONResponse:
    """Fetch any optionable ticker's CBOE chain and compute its positioning.

    Modelled on the SPY route but takes a ``symbol`` query param. A clean
    "not found" (bad shape or no usable options data) is persisted as a normal
    ``status="ok"`` message state so the panel shows a tidy note rather than an
    error badge; only genuine fetch/compute failures keep the cached snapshot
    behind an error badge. One store key -> the panel reloads the last queried
    ticker on startup.
    """
    out = {}
    sym = (symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z.]{1,6}", sym):
        payload = {"symbol": sym, "not_found": True,
                   "message": f"'{symbol}' is not a valid ticker."}
        out["ticker_positioning"] = store.save_panel(
            "ticker_positioning", payload, status="ok")
        return JSONResponse(out)
    try:
        payload = ticker_positioning.refresh(sym)
        out["ticker_positioning"] = store.save_panel(
            "ticker_positioning", payload, status="ok")
    except ticker_positioning.NotFound:
        payload = {"symbol": sym, "not_found": True,
                   "message": f"No optionable data found for {sym}."}
        out["ticker_positioning"] = store.save_panel(
            "ticker_positioning", payload, status="ok")
    except Exception as exc:
        store.update_status("ticker_positioning", "error", str(exc))
        out["ticker_positioning"] = store.get_panel("ticker_positioning")
    return JSONResponse(out)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
