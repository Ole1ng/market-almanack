"""RSS news aggregation via feedparser.

Each panel aggregates one or more free RSS feeds. We lean on Google News RSS
search endpoints because they are key-free, stable, and let us target the
exact topics each panel needs, supplemented by a couple of reliable direct
feeds (CNBC, MarketWatch, OilPrice).

Items are deduplicated by link, sorted newest first, and capped per panel.
No API keys, no auth — just HTTP GET of public RSS.
"""

from __future__ import annotations

import calendar
import socket
import time
from urllib.parse import quote_plus

import feedparser

MAX_ITEMS = 30
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) MarketAlmanack/1.0"
)

# feedparser uses urllib under the hood; cap how long any single feed can hang.
socket.setdefaulttimeout(20)


def _gnews(query: str) -> str:
    """Build a Google News RSS search URL for the last ~7 days."""
    q = quote_plus(f"{query} when:7d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


# Panel -> list of RSS feed URLs.
FEEDS: dict[str, list[str]] = {
    "news_us": [
        "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # CNBC Top News
        "https://www.cnbc.com/id/20910258/device/rss/rss.html",   # CNBC Markets
        _gnews("Federal Reserve OR FOMC OR stock market OR earnings OR "
               "US economy OR inflation OR jobs report"),
    ],
    "news_global": [
        _gnews("China economy OR ECB OR European Central Bank OR Bank of Japan "
               "OR OPEC decision OR geopolitics OR US trade policy OR tariffs"),
        _gnews("Europe markets OR China markets OR global economy "
               "impact US stocks"),
    ],
    "news_energy": [
        "https://oilprice.com/rss/main",
        _gnews("crude oil OR WTI OR Brent OR natural gas OR Henry Hub OR "
               "uranium OR LNG OR energy prices"),
    ],
    "news_precious": [
        _gnews("gold price OR silver price OR platinum OR palladium OR "
               "Comex OR bullion OR precious metals"),
    ],
    "news_commodities": [
        _gnews("wheat OR soybeans OR corn OR coffee OR cocoa OR sugar OR "
               "orange juice OR lumber prices"),
        _gnews("copper OR aluminium OR zinc OR nickel OR tin OR iron ore OR "
               "steel prices OR live cattle OR tungsten"),
    ],
}


def _entry_time(entry) -> float:
    """Return epoch seconds (UTC) for an entry, or 0 if unknown."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return calendar.timegm(t)
    return 0.0


def _source_of(entry, feed) -> str:
    # Google News nests the true source under entry.source.title.
    src = getattr(entry, "source", None)
    if src is not None and getattr(src, "title", None):
        return src.title
    title = getattr(feed.feed, "title", "") if feed else ""
    return title or "RSS"


def fetch_panel(panel_key: str) -> list[dict]:
    """Fetch + merge + dedupe + sort all feeds for one panel.

    Individual feed failures are swallowed so one bad feed does not blank the
    panel; if *all* feeds fail and yield nothing, raises RuntimeError so the
    caller can keep the stale cache and show an error badge.
    """
    urls = FEEDS[panel_key]
    seen: set[str] = set()
    items: list[dict] = []
    errors = 0

    for url in urls:
        try:
            feed = feedparser.parse(url, agent=_USER_AGENT)
        except Exception:
            errors += 1
            continue
        if getattr(feed, "bozo", 0) and not getattr(feed, "entries", None):
            errors += 1
            continue

        for entry in feed.entries:
            link = getattr(entry, "link", None)
            title = (getattr(entry, "title", "") or "").strip()
            if not link or not title or link in seen:
                continue
            seen.add(link)
            source = _source_of(entry, feed)
            # Google News appends " - Publisher" to every title; strip it so
            # source names don't leak into the theme/entity analysis.
            if source and title.endswith(" - " + source):
                title = title[: -(len(source) + 3)].strip()
            items.append(
                {
                    "title": title,
                    "link": link,
                    "source": source,
                    "published": _entry_time(entry),
                    "summary": (getattr(entry, "summary", "") or "").strip(),
                }
            )

    if not items and errors == len(urls):
        raise RuntimeError(f"all {errors} feed(s) failed for {panel_key}")

    items.sort(key=lambda it: it["published"], reverse=True)
    return items[:MAX_ITEMS]
