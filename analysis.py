"""Rule-based, fully offline headline analysis (no LLM).

Pipeline per headline corpus:
  1. Tokenise & clean  - lowercase, strip punctuation, drop stopwords
                         (NLTK English + finance-noise list).
  2. Sentiment         - VADER compound per headline, bucketed + aggregated.
  3. Theme extraction  - top unigrams + bigrams via CountVectorizer(min_df=2).
  4. Entity spotting   - $TICKER + repeated uppercase tokens + per-panel watchlist.
  5. Salient headlines - sentiment magnitude x count of top-theme terms present.

Everything degrades gracefully on an empty / tiny corpus.
"""

from __future__ import annotations

import re
from collections import Counter

from sklearn.feature_extraction.text import CountVectorizer
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# --------------------------------------------------------------------------- #
# Stopwords
# --------------------------------------------------------------------------- #

_FINANCE_NOISE = {
    "market", "markets", "stock", "stocks", "share", "shares", "today",
    "report", "reports", "reported", "says", "said", "say", "year", "years",
    "week", "weeks", "month", "months", "day", "days", "new", "update",
    "updates", "latest", "news", "amid", "could", "would", "may", "might",
    "set", "see", "sees", "get", "gets", "u", "s", "us", "vs", "via",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "june", "july",
    "august", "september", "october", "november", "december",
    "inc", "corp", "ltd", "co", "group", "plc", "billion", "million",
    "high", "low", "close", "open", "rise", "rises", "fall", "falls",
    "near", "back", "first", "top", "key", "amp", "com", "www", "http",
    "https", "campaign",
}


def _load_stopwords() -> set[str]:
    """NLTK English stopwords + finance noise. Falls back if NLTK is offline."""
    base: set[str] = set()
    try:
        import nltk
        from nltk.corpus import stopwords

        try:
            base = set(stopwords.words("english"))
        except LookupError:
            nltk.download("stopwords", quiet=True)
            base = set(stopwords.words("english"))
    except Exception:
        # Minimal hardcoded fallback so analysis still runs offline.
        base = {
            "the", "a", "an", "and", "or", "but", "if", "to", "of", "in", "on",
            "for", "with", "as", "at", "by", "from", "is", "are", "was", "were",
            "be", "been", "it", "its", "this", "that", "these", "those", "has",
            "have", "had", "will", "after", "over", "up", "down", "out", "into",
            "about", "more", "than", "then", "you", "your", "he", "she", "they",
            "we", "i", "not", "no", "all", "can", "his", "her",
        }
    return base | _FINANCE_NOISE


STOPWORDS = _load_stopwords()
_analyzer = SentimentIntensityAnalyzer()

# Per-panel watchlists of known relevant names (case-insensitive word match).
WATCHLISTS = {
    "macro": [
        "Fed", "FOMC", "Powell", "ECB", "BoJ", "OPEC", "China", "Treasury",
        "inflation", "CPI", "GDP", "tariff", "tariffs", "recession", "jobs",
        "rates", "yield", "Nvidia", "Apple", "earnings", "dollar",
    ],
    "energy": [
        "WTI", "Brent", "OPEC", "crude", "oil", "natural gas", "Henry Hub",
        "uranium", "LNG", "gas", "diesel", "gasoline", "shale", "Saudi",
    ],
    "precious": [
        "gold", "silver", "platinum", "palladium", "Comex", "bullion",
        "miners", "ounce", "spot",
    ],
    "commodities": [
        "wheat", "soybeans", "soybean", "corn", "coffee", "cocoa", "sugar",
        "orange juice", "lumber", "cattle", "copper", "aluminium", "aluminum",
        "zinc", "nickel", "titanium", "tungsten", "tin", "iron ore", "steel",
    ],
}

_TICKER_RE = re.compile(r"\$[A-Z]{1,5}\b")
_UPPER_RE = re.compile(r"\b[A-Z]{1,5}\b")
_WORD_RE = re.compile(r"[a-z][a-z'&-]+")


# --------------------------------------------------------------------------- #
# Pipeline steps
# --------------------------------------------------------------------------- #

def _sentiment(headlines: list[str]) -> dict:
    if not headlines:
        return {
            "tone": "No data", "mean": 0.0,
            "pos_pct": 0, "neg_pct": 0, "neu_pct": 0,
            "pos": 0, "neg": 0, "neu": 0, "n": 0,
        }
    scores = [_analyzer.polarity_scores(h)["compound"] for h in headlines]
    pos = sum(1 for s in scores if s >= 0.05)
    neg = sum(1 for s in scores if s <= -0.05)
    neu = len(scores) - pos - neg
    mean = sum(scores) / len(scores)
    n = len(scores)
    if mean >= 0.05:
        tone = "Bullish"
    elif mean <= -0.05:
        tone = "Bearish"
    else:
        tone = "Mixed"
    return {
        "tone": tone,
        "mean": round(mean, 3),
        "pos_pct": round(100 * pos / n),
        "neg_pct": round(100 * neg / n),
        "neu_pct": round(100 * neu / n),
        "pos": pos, "neg": neg, "neu": neu, "n": n,
    }


def _themes(headlines: list[str], top_n: int = 15) -> list[dict]:
    """Top unigrams + bigrams by frequency via CountVectorizer."""
    if len(headlines) < 2:
        return []
    for min_df in (2, 1):  # relax for tiny corpora
        try:
            vec = CountVectorizer(
                ngram_range=(1, 2),
                min_df=min_df,
                stop_words=list(STOPWORDS),
                token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z'&-]+\b",
            )
            matrix = vec.fit_transform(headlines)
        except ValueError:
            continue
        counts = matrix.sum(axis=0).A1
        terms = vec.get_feature_names_out()
        pairs = sorted(zip(terms, counts), key=lambda p: p[1], reverse=True)
        return [{"term": t, "count": int(c)} for t, c in pairs[:top_n]]
    return []


def _entities(headlines: list[str], watchlist: list[str],
              top_n: int = 10) -> list[dict]:
    counts: Counter = Counter()
    joined_lower = " \n ".join(h.lower() for h in headlines)

    # 1. $TICKER patterns + repeated uppercase tokens.
    upper_counts: Counter = Counter()
    for h in headlines:
        for m in _TICKER_RE.findall(h):
            counts[m] += 1
        for tok in _UPPER_RE.findall(h):
            if tok in STOPWORDS or {tok.lower()} & STOPWORDS:
                continue
            upper_counts[tok] += 1
    for tok, c in upper_counts.items():
        if c >= 2:  # only surface uppercase tokens seen 2+ times
            counts[tok] += c

    # 2. Hardcoded watchlist (case-insensitive word/phrase match).
    for name in watchlist:
        n = len(re.findall(r"\b" + re.escape(name.lower()) + r"\b", joined_lower))
        if n:
            counts[name] += n

    pairs = sorted(counts.items(), key=lambda p: p[1], reverse=True)
    return [{"entity": e, "count": int(c)} for e, c in pairs[:top_n]]


def _salient(items: list[dict], themes: list[dict], top_n: int = 5) -> list[dict]:
    """Score each headline by sentiment magnitude x #top-theme terms present."""
    theme_terms = [t["term"] for t in themes]
    scored = []
    for it in items:
        title = it["title"]
        low = title.lower()
        mag = abs(_analyzer.polarity_scores(title)["compound"])
        hits = sum(1 for term in theme_terms if term in low)
        score = mag * (1 + hits)  # +1 so non-theme but emotive headlines rank
        scored.append((score, it))
    scored.sort(key=lambda p: p[0], reverse=True)
    return [
        {"title": it["title"], "link": it["link"], "source": it.get("source", ""),
         "score": round(score, 3)}
        for score, it in scored[:top_n]
    ]


def analyse_corpus(items: list[dict], watchlist_key: str,
                   themes_n: int = 15, salient_n: int = 5,
                   entities_n: int = 10) -> dict:
    """Run the full pipeline on one corpus of news items."""
    headlines = [it["title"] for it in items if it.get("title")]
    watchlist = WATCHLISTS.get(watchlist_key, [])
    return {
        "count": len(headlines),
        "sentiment": _sentiment(headlines),
        "themes": _themes(headlines, themes_n),
        "entities": _entities(headlines, watchlist, entities_n),
        "salient": _salient(items, _themes(headlines, themes_n), salient_n),
    }


# --------------------------------------------------------------------------- #
# Panel builders
# --------------------------------------------------------------------------- #

CAVEAT = ("Extractive analysis — frequency and sentiment of headlines, not "
          "interpretation. Themes show what is being reported, not what it implies.")


def build_macro(news_us: list[dict], news_global: list[dict]) -> dict:
    """Panel 8 — combined US Markets + Global->US headlines."""
    combined = (news_us or []) + (news_global or [])
    result = analyse_corpus(combined, "macro")
    result["caveat"] = CAVEAT
    result["empty"] = result["count"] == 0
    return result


def build_commodity(news_energy: list[dict], news_precious: list[dict],
                    news_other: list[dict]) -> dict:
    """Panel 9 — per-complex breakdown + cross-complex summary."""
    energy = news_energy or []
    precious = news_precious or []
    other = news_other or []

    blocks = {
        "energy": analyse_corpus(energy, "energy", themes_n=10, salient_n=3),
        "precious": analyse_corpus(precious, "precious", themes_n=10, salient_n=3),
        "other": analyse_corpus(other, "commodities", themes_n=10, salient_n=3),
    }

    combined = energy + precious + other
    cross = analyse_corpus(combined, "commodities", themes_n=5, salient_n=5)

    return {
        "blocks": blocks,
        "cross": cross,
        "caveat": CAVEAT,
        "empty": (len(combined) == 0),
    }
