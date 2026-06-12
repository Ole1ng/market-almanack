"""Finviz screeners via the finvizfinance package.

Filter dictionaries use the exact human-readable keys/values that
finvizfinance's Custom screener expects (verified against
finvizfinance.constants.util_dict['filter']). The Custom screener is used
instead of Overview so we can pull the richer columns the dashboard wants
(Rel Volume, Float, Beta, Perf Week, Perf Month).
"""

from __future__ import annotations

import warnings

from finvizfinance.screener.custom import Custom

# Safety cap on pages (20 rows/page) so a runaway filter can't fetch forever.
_MAX_PAGES = 60

# Column indices from finvizfinance.constants.CUSTOM_SCREENER_COLUMNS.
# 1 Ticker, 2 Company, 3 Sector, 42 Perf Week, 43 Perf Month, 48 Beta,
# 25 Shares Float, 64 Relative Volume, 65 Price, 66 Change, 67 Volume
_COLUMNS = [1, 2, 3, 42, 43, 48, 25, 64, 65, 66, 67]

# Order in which we present columns to the frontend.
COLUMN_ORDER = [
    "Ticker",
    "Company",
    "Sector",
    "Price",
    "Change",      # 1-day change (fraction, e.g. 0.10 = +10%)
    "Perf Week",   # Change % 1 week
    "Perf Month",  # Change % 1 month
    "Volume",
    "Rel Volume",
    "Float",
    "Beta",
]

DAYTRADING_FILTERS = {
    "Price": "Over $5",
    "Average Volume": "Over 500K",
    "Relative Volume": "Over 2",
    "Change": "Up",
    "Gap": "Up",
    "20-Day Simple Moving Average": "Price above SMA20",
    "50-Day Simple Moving Average": "Price above SMA50",
    "Float": "Under 50M",
    "Beta": "Over 1.5",
}

SWING_FILTERS = {
    "Price": "Over $10",
    "Average Volume": "Over 500K",
    "Relative Volume": "Over 1.5",
    "20-Day Simple Moving Average": "Price above SMA20",
    "50-Day Simple Moving Average": "Price above SMA50",
    "200-Day Simple Moving Average": "Price above SMA200",
    "Performance": "Month Up",
    "52-Week High/Low": "0-10% below High",
    "RSI (14)": "Not Overbought (<60)",
}


def _run(filters: dict) -> list[dict]:
    """Fetch every matching row, paginating explicitly.

    finvizfinance's built-in pagination relies on parsing the page-count
    widget, which Finviz intermittently omits — silently capping results at
    the first 20. We instead request pages one at a time and stop only when a
    page is empty or adds no new tickers, so all matches are returned
    regardless of that flakiness.
    """
    screener = Custom()
    screener.set_filter(filters_dict=filters)

    rows: list[dict] = []
    seen: set[str] = set()
    cols: list[str] | None = None

    for page in range(1, _MAX_PAGES + 1):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # "limit ignored when page set"
                df = screener.screener_view(
                    columns=_COLUMNS, verbose=0, select_page=page, sleep_sec=0.5)
        except Exception:
            break
        if df is None or len(df) == 0:
            break

        if cols is None:
            # finviz column labels are short forms ('Rel Volume', 'Float', ...).
            cols = [c for c in COLUMN_ORDER if c in df.columns]

        new = 0
        for _, r in df.iterrows():
            tkr = r.get("Ticker")
            if not tkr or tkr in seen:
                continue
            seen.add(tkr)
            new += 1
            row = {}
            for c in cols:
                val = r[c]
                # NaN -> None for clean JSON; keep numbers as numbers.
                row[c] = None if val != val else (val.item() if hasattr(val, "item") else val)
            rows.append(row)

        # Stop on the last (partial) page, or if a flaky repeat added nothing.
        if new == 0 or len(df) < screener.size:
            break

    return rows


def run_daytrading() -> dict:
    return {"columns": COLUMN_ORDER, "rows": _run(DAYTRADING_FILTERS),
            "filters": DAYTRADING_FILTERS}


def run_swing() -> dict:
    return {"columns": COLUMN_ORDER, "rows": _run(SWING_FILTERS),
            "filters": SWING_FILTERS}
