# Market Almanack

A **local, offline market dashboard** that runs in your browser at
`http://localhost:8000`. It combines two Finviz screeners, five RSS news
feeds, and two rule-based (no-LLM) news analyses into a single terminal-style
page.

- **No API keys. No LLM calls.** Everything runs offline aside from the
  RSS / Finviz HTTP fetches the buttons trigger.
- **Nothing auto-refreshes.** You decide when to fetch.
- **Data persists** to a local SQLite file (`almanack.db`), so reopening the
  page immediately renders your last session before any new fetch. Every panel
  shows a "last updated" time, and failed fetches keep the stale data behind an
  error/stale badge instead of blanking the panel.

## Quick start

```bash
cd market_almanack
pip install -r requirements.txt
python app.py
```

Then open <http://localhost:8000>. On first run the app auto-downloads the
NLTK stopword list; no manual setup needed.

## The three buttons

| Button | What it does | Panels |
|--------|--------------|--------|
| **Refresh Screeners** | Re-runs both Finviz screeners (and upcoming earnings, since its watchlist is partly derived from the screeners) | 1–2, 10 |
| **Refresh Earnings** | Re-fetches upcoming earnings for the watchlist only | 10 |
| **Refresh News** | Re-fetches all RSS feeds | 3–7 |
| **Update Analysis** | Re-runs the analyses on the **currently cached** news | 8–9 |

`Update Analysis` reads whatever news is already stored, so refresh news first
if you want the analysis to reflect the latest headlines.

## Panels

1. **Daytrading Screener** — Finviz: price > $5, avg vol > 500K, rel vol > 2,
   change up, gap up, price above SMA20 & SMA50, float < 50M, beta > 1.5.
2. **Swing Screener** — price > $10, avg vol > 500K, rel vol > 1.5, above
   SMA20/50/200, month up, within 0–10% of 52-week high, RSI(14) not overbought.
   Both are sortable tables (click or focus + Enter on any header).
3. **US Markets** — Fed/macro/equities/earnings (CNBC, MarketWatch, Google News).
4. **Global → US** — China, ECB, BoJ, OPEC, trade policy and other
   international news affecting US markets.
5. **Energy** — oil, natural gas, uranium, LNG (OilPrice + Google News).
6. **Precious Metals** — gold, silver, platinum, palladium.
7. **Other Commodities** — grains, softs, base & industrial metals, lumber, etc.
8. **Macro Overview** — analysis of panels 3+4.
9. **Commodity Overview** — analysis of panels 5/6/7, broken down per complex
   plus a cross-complex summary.
10. **Upcoming Earnings** — `yfinance` earnings dates for a watchlist within
    the next 14 days, grouped by date with sticky day headers. The watchlist is
    the **S&P 500 + Nasdaq-100 union** (~520 tickers, baked into
    `watchlist_constituents.py`) plus whatever the two screeners return, so it
    covers essentially every notable US large/mid-cap reporting in the window.
    Shows ticker (→ Yahoo Finance), company, session (BMO/AMC), EPS estimate,
    and a `DAY`/`SWING`/`BOTH` badge marking tickers you're already screening.
    Fetches run in parallel (`ThreadPoolExecutor`, 16 workers, ~60–90s for the
    full list); company names are cached separately so later refreshes are
    faster. Tunable constants live in `earnings.py` (`EARNINGS_LOOKAHEAD_DAYS`,
    `EARNINGS_REFRESH_WITH_SCREENERS`). Regenerate constituents with
    `python tools/refresh_constituents.py`.

    > Note: earnings dates/estimates come straight from yfinance and
    > occasionally carry upstream data quirks (an odd EPS figure, a spun-off
    > ticker). They're displayed as-is, not corrected.

## How the analysis works (panels 8–9)

Pure-Python extractive analysis, fully offline:

1. **Tokenise & clean** — lowercase, strip punctuation, drop NLTK English
   stopwords + a finance-noise list.
2. **Sentiment** — VADER compound per headline, bucketed (≥0.05 positive,
   ≤−0.05 negative) and aggregated into a tone (Bullish / Bearish / Mixed).
3. **Themes** — top unigrams + bigrams via `CountVectorizer(ngram_range=(1,2),
   min_df=2)`.
4. **Entities** — `$TICKER` patterns, repeated uppercase tokens, and a
   per-panel watchlist of known names (Fed, ECB, OPEC, WTI, gold, copper…).
5. **Salient headlines** — scored by sentiment magnitude × number of top-theme
   terms present.

> **Caveat shown in-panel:** *Extractive analysis — frequency and sentiment of
> headlines, not interpretation. Themes show what is being reported, not what
> it implies.*

## Project layout

```
market_almanack/
├── app.py            FastAPI app + JSON API + startup (DB init, NLTK download)
├── store.py          SQLite persistence (one row per panel)
├── screeners.py      Finviz Custom screener filters & column mapping
├── earnings.py       yfinance earnings watchlist + parallel fetch
├── watchlist_constituents.py   S&P 500 + Nasdaq-100 union (baked)
├── tools/refresh_constituents.py   regenerate the constituents list
├── news.py           RSS feed config + fetch / dedupe / sort
├── analysis.py       VADER + CountVectorizer + entity-spotting pipeline
├── static/           index.html, style.css, app.js (the dashboard UI)
├── requirements.txt
└── almanack.db       created on first run (gitignored)
```

## Notes

- The dashboard is keyboard navigable, uses semantic HTML + ARIA live regions,
  and meets WCAG AA contrast on its dark terminal theme.
- If a feed or screener fails, that panel keeps its last good data and shows a
  `stale` (or `error`, if never fetched) badge; the rest of the page is
  unaffected.
- Analysis on an empty corpus is handled gracefully ("No data yet — refresh
  news first").
