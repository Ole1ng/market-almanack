"""SQLite-backed persistence for Market Almanack.

Every panel stores a single JSON payload plus metadata (timestamp / status /
error). This makes reload-on-startup trivial: the frontend asks for the full
state and renders whatever was saved last session before any new fetch runs.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).with_name("almanack.db")

# Panel keys are the contract shared with the frontend.
PANEL_KEYS = [
    "screener_day",
    "screener_swing",
    "news_us",
    "news_global",
    "news_energy",
    "news_precious",
    "news_commodities",
    "analysis_macro",
    "analysis_commodity",
    "earnings",
    "spy_positioning",
]

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS panels (
                panel_key   TEXT PRIMARY KEY,
                payload     TEXT,           -- JSON
                status      TEXT,           -- 'ok' | 'error' | 'empty'
                error       TEXT,           -- last error message, if any
                updated_at  REAL            -- epoch seconds (UTC)
            )
            """
        )
        # Long-lived ticker -> company name cache (rarely changes; the yfinance
        # .info call is slow, so we avoid re-fetching names every refresh).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS name_cache (
                ticker  TEXT PRIMARY KEY,
                name    TEXT
            )
            """
        )


def save_panel(
    panel_key: str,
    payload: Any,
    status: str = "ok",
    error: str | None = None,
    updated_at: float | None = None,
) -> dict:
    """Persist a panel. Returns the stored record (as the API exposes it)."""
    if updated_at is None:
        updated_at = time.time()
    record = {
        "payload": payload,
        "status": status,
        "error": error,
        "updated_at": updated_at,
    }
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO panels (panel_key, payload, status, error, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(panel_key) DO UPDATE SET
                payload=excluded.payload,
                status=excluded.status,
                error=excluded.error,
                updated_at=excluded.updated_at
            """,
            (panel_key, json.dumps(payload), status, error, updated_at),
        )
    return {"panel_key": panel_key, **record}


def update_status(panel_key: str, status: str, error: str | None) -> None:
    """Mark a panel's status/error without touching its cached payload.

    Used on fetch failure so the stale payload stays visible behind an
    error badge.
    """
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE panels SET status=?, error=?, updated_at=? WHERE panel_key=?",
            (status, error, time.time(), panel_key),
        )


def get_panel(panel_key: str) -> dict | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM panels WHERE panel_key=?", (panel_key,)
        ).fetchone()
    if row is None:
        return None
    return {
        "panel_key": row["panel_key"],
        "payload": json.loads(row["payload"]) if row["payload"] else None,
        "status": row["status"],
        "error": row["error"],
        "updated_at": row["updated_at"],
    }


def get_all() -> dict[str, dict | None]:
    """Return every known panel keyed by panel_key (None if never fetched)."""
    return {key: get_panel(key) for key in PANEL_KEYS}


# --------------------------------------------------------------------------- #
# Company-name cache
# --------------------------------------------------------------------------- #

def get_names(tickers) -> dict[str, str]:
    tickers = list(tickers)
    if not tickers:
        return {}
    placeholders = ",".join("?" for _ in tickers)
    with _lock, _connect() as conn:
        rows = conn.execute(
            f"SELECT ticker, name FROM name_cache WHERE ticker IN ({placeholders})",
            tickers,
        ).fetchall()
    return {r["ticker"]: r["name"] for r in rows}


def save_name(ticker: str, name: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO name_cache (ticker, name) VALUES (?, ?)
            ON CONFLICT(ticker) DO UPDATE SET name=excluded.name
            """,
            (ticker, name),
        )
