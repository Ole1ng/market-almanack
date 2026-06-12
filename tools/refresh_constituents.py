"""Regenerate market_almanack/watchlist_constituents.py from Wikipedia.

The earnings watchlist baseline is the S&P 500 + Nasdaq-100 union, baked into
a static module so the app stays offline-first. Constituents change only a few
times a year; run this when you want to refresh them:

    python tools/refresh_constituents.py

Requires `requests` and `pandas` (already in the project env).
"""

from __future__ import annotations

import datetime
import io
import textwrap
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).resolve().parent.parent / "watchlist_constituents.py"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36"
}


def _tables(url: str) -> list[pd.DataFrame]:
    html = requests.get(url, headers=HEADERS, timeout=30).text
    return pd.read_html(io.StringIO(html))


def _norm(sym: str) -> str:
    # yfinance uses '-' for class shares (BRK-B); Wikipedia uses '.'.
    return str(sym).replace(".", "-").strip()


def fetch_union() -> list[str]:
    sp = _tables("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
    sp_syms = [_norm(s) for s in sp["Symbol"]]

    ndx_syms: list[str] | None = None
    for t in _tables("https://en.wikipedia.org/wiki/Nasdaq-100"):
        cols = {str(c).lower(): str(c) for c in t.columns}
        key = cols.get("ticker") or cols.get("symbol")
        if key and 80 <= len(t) <= 130:
            ndx_syms = [_norm(s) for s in t[key]]
            break
    if not ndx_syms:
        raise RuntimeError("Could not locate the Nasdaq-100 constituents table")

    union = sorted(set(sp_syms) | set(ndx_syms))
    union = [u for u in union
             if u and u.replace("-", "").isalnum() and 1 <= len(u) <= 6 and u != "NAN"]
    return union


def write_module(tickers: list[str]) -> None:
    wrapped = textwrap.wrap(", ".join(f'"{t}"' for t in tickers), 88)
    body = "\n".join("    " + line for line in wrapped)
    OUT.write_text(
        f'''"""S&P 500 + Nasdaq-100 constituents (union), baked at build time.

Generated {datetime.date.today().isoformat()} from Wikipedia. Constituents change
only a few times a year; regenerate with tools/refresh_constituents.py if needed.
{len(tickers)} tickers. yfinance class-share format ('.' -> '-', e.g. BRK-B).
"""

SP500_NDX100 = [
{body}
]
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    syms = fetch_union()
    write_module(syms)
    print(f"Wrote {OUT} with {len(syms)} tickers")
