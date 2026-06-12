"""Upcoming earnings via yfinance (no API key).

There is no single "all upcoming earnings" endpoint, so we maintain a
watchlist (screener tickers + a large-cap baseline) and query each ticker's
earnings calendar in parallel, keeping only dates inside a forward window.

Results are cached in the shared SQLite store and reloaded on open, exactly
like every other panel. Company names are cached separately since they rarely
change and `.info` is the slow call.
"""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

import yfinance as yf

import store
from watchlist_constituents import SP500_NDX100

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

EARNINGS_LOOKAHEAD_DAYS = 14
# When True, the screener refresh also refreshes earnings (the watchlist is
# partly derived from screener output, so they stay in sync).
EARNINGS_REFRESH_WITH_SCREENERS = True
# More workers than the original ~100-ticker design, since the watchlist is now
# the full S&P 500 + Nasdaq-100 (~500+ tickers); keeps refresh ~60-90s.
MAX_WORKERS = 16

ET = ZoneInfo("America/New_York")

# Baseline watchlist: full S&P 500 + Nasdaq-100 union, so the panel covers
# essentially every notable US large/mid-cap reporting in the window — not just
# a handful. Regenerate with tools/refresh_constituents.py.
BASELINE_TICKERS = SP500_NDX100


# --------------------------------------------------------------------------- #
# Watchlist
# --------------------------------------------------------------------------- #

def _screener_tickers(panel_key: str) -> list[str]:
    rec = store.get_panel(panel_key)
    payload = (rec or {}).get("payload") or {}
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not rows:
        return []
    return [r.get("Ticker") for r in rows if r.get("Ticker")]


def build_watchlist() -> tuple[list[str], dict[str, set[str]]]:
    """Return (tickers, membership) where membership[ticker] is a set of the
    sources it came from: {'DAY'}, {'SWING'}, both, or empty for baseline."""
    day = set(_screener_tickers("screener_day"))
    swing = set(_screener_tickers("screener_swing"))
    tickers = sorted(set(BASELINE_TICKERS) | day | swing)

    membership: dict[str, set[str]] = {}
    for tkr in tickers:
        tags = set()
        if tkr in day:
            tags.add("DAY")
        if tkr in swing:
            tags.add("SWING")
        membership[tkr] = tags
    return tickers, membership


def _screener_badge(tags: set[str]) -> str:
    if "DAY" in tags and "SWING" in tags:
        return "BOTH"
    if "DAY" in tags:
        return "DAY"
    if "SWING" in tags:
        return "SWING"
    return ""


# --------------------------------------------------------------------------- #
# Per-ticker fetch
# --------------------------------------------------------------------------- #

def _classify_time(ts) -> str:
    """Map an earnings timestamp's time-of-day to a session label."""
    h, m = ts.hour, ts.minute
    if h == 0 and m == 0:
        return "Time Not Supplied"
    if h < 12:
        return "Before Market Open"
    if h >= 16:
        return "After Market Close"
    return "Time Not Supplied"


def _to_et(ts):
    """Normalise a pandas Timestamp / datetime to US Eastern."""
    if ts.tzinfo is None:
        return ts.tz_localize(ET) if hasattr(ts, "tz_localize") else ts.replace(tzinfo=ET)
    return ts.tz_convert(ET) if hasattr(ts, "tz_convert") else ts.astimezone(ET)


def fetch_ticker(symbol: str, today: dt.date, horizon: dt.date) -> list[dict]:
    """Return earnings rows for one ticker within [today, horizon].

    Tries get_earnings_dates first (richer, has time component); falls back to
    .calendar. Any failure yields an empty list so one bad ticker never kills
    the batch.
    """
    rows: list[dict] = []
    t = yf.Ticker(symbol)

    # --- primary: get_earnings_dates ---
    try:
        df = t.get_earnings_dates(limit=8)
        if df is not None and len(df):
            for ts, data in df.iterrows():
                et = _to_et(ts)
                d = et.date()
                if today <= d <= horizon:
                    eps = data.get("EPS Estimate")
                    rows.append(_row(symbol, et, d, _classify_time(et),
                                     None if eps != eps else eps))  # NaN -> None
    except Exception:
        pass

    # --- fallback: .calendar (date-only) ---
    if not rows:
        try:
            cal = t.calendar or {}
            eps = cal.get("Earnings Average")
            for d in cal.get("Earnings Date", []) or []:
                if isinstance(d, dt.datetime):
                    d = d.date()
                if today <= d <= horizon:
                    et = dt.datetime(d.year, d.month, d.day, tzinfo=ET)
                    rows.append(_row(symbol, et, d, "Time Not Supplied", eps))
        except Exception:
            pass

    return rows


def _row(symbol, et, d, when, eps) -> dict:
    return {
        "ticker": symbol,
        "date": d.isoformat(),
        "date_label": d.strftime("%b %d").replace(" 0", " "),
        "dow": d.strftime("%a"),
        "ts": et.timestamp(),
        "time": when,
        "eps_estimate": round(float(eps), 2) if eps is not None else None,
    }


# --------------------------------------------------------------------------- #
# Company-name cache
# --------------------------------------------------------------------------- #

def _resolve_name(symbol: str) -> str | None:
    try:
        name = yf.Ticker(symbol).info.get("shortName")
        return name or None
    except Exception:
        return None


def _attach_names(rows: list[dict]) -> None:
    """Fill company names, fetching only those not already cached."""
    symbols = {r["ticker"] for r in rows}
    cached = store.get_names(symbols)
    missing = [s for s in symbols if not cached.get(s)]

    if missing:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_resolve_name, s): s for s in missing}
            for fut in as_completed(futures):
                sym = futures[fut]
                name = fut.result()
                if name:
                    store.save_name(sym, name)
                    cached[sym] = name

    for r in rows:
        r["company"] = cached.get(r["ticker"]) or r["ticker"]


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def fetch_earnings() -> dict:
    """Fetch upcoming earnings for the whole watchlist (parallelised)."""
    tickers, membership = build_watchlist()
    today = dt.datetime.now(ET).date()
    horizon = today + dt.timedelta(days=EARNINGS_LOOKAHEAD_DAYS)

    all_rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_ticker, s, today, horizon): s for s in tickers}
        for fut in as_completed(futures):
            try:
                all_rows.extend(fut.result())
            except Exception:
                pass

    _attach_names(all_rows)

    for r in all_rows:
        r["in_screener"] = _screener_badge(membership.get(r["ticker"], set()))

    all_rows.sort(key=lambda r: (r["ts"], r["ticker"]))

    return {
        "rows": all_rows,
        "lookahead_days": EARNINGS_LOOKAHEAD_DAYS,
        "watchlist_size": len(tickers),
    }
