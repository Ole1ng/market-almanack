"""Tests for the generic ticker positioning panel.

Mirrors the SPY tests' spirit with synthetic CBOE chains: a valid chain yields a
regime + commentary, and empty/garbage/no-spot snapshots raise NotFound (the
panel's clean "not found" path). Also checks the auto-scaling plumbing (the
private ``_thresh`` key is stripped) and the dynamic strike bucket. Does not
touch test_spy_positioning.py.

Run standalone:  python -m panels.test_ticker_positioning
Or with pytest:  pytest panels/test_ticker_positioning.py
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from panels import ticker_positioning as tp


def _raises(exc, fn, *args, **kwargs):
    """pytest-free assertion that ``fn`` raises ``exc`` (the project ships no
    pytest dependency; the SPY tests run via a standalone runner too)."""
    try:
        fn(*args, **kwargs)
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__} from {fn.__name__}")

NOW = datetime(2026, 6, 16, 15, 0, 0, tzinfo=timezone.utc)
EXPIRY = date(2026, 7, 17)  # ~31 days out, inside the 90-day window


def _occ(sym: str, expiry: date, right: str, strike: float) -> str:
    return f"{sym}{expiry.strftime('%y%m%d')}{right}{int(round(strike * 1000)):08d}"


def _chain(symbol="AAPL", spot=150.0, lo=140, hi=160, step=1, extra_options=None):
    """Synthetic chain: calls + puts on every strike in [lo, hi] at `step`."""
    options = []
    k = lo
    while k <= hi:
        # plausible greeks; calls delta>0, puts delta<0, both gamma>0
        options.append({"option": _occ(symbol, EXPIRY, "C", k),
                        "open_interest": 1000, "gamma": 0.02,
                        "delta": 0.5, "iv": 0.30})
        options.append({"option": _occ(symbol, EXPIRY, "P", k),
                        "open_interest": 1200, "gamma": 0.02,
                        "delta": -0.5, "iv": 0.32})
        k += step
    if extra_options:
        options.extend(extra_options)
    return {"timestamp": "2026-06-16T14:55:00",
            "data": {"current_price": spot, "options": options}}


# --------------------------------------------------------------------------- #
# Valid chain
# --------------------------------------------------------------------------- #

def test_valid_chain_produces_regime_and_commentary():
    out = tp.compute(_chain(), "AAPL", now=NOW)
    assert out["symbol"] == "AAPL"
    assert out["regime"] in ("positive", "negative")
    assert out["spot"] == 150.0
    c = out["commentary"]
    assert c["headline"]
    assert len(c["sentences"]) >= 1
    # auto-scaling plumbing must not leak to the client
    assert "_thresh" not in out
    # chart + dynamic bucket present
    assert out["chart"]
    assert out["bucket"] == 1.0  # modal increment of the $1-spaced synthetic chain


def test_dynamic_bucket_scales_with_spacing():
    # a $900 name with $5 strike spacing -> bucket 5, not stuck at 1
    out = tp.compute(_chain(symbol="NVDA", spot=900.0, lo=860, hi=940, step=5),
                     "NVDA", now=NOW)
    assert out["bucket"] == 5.0


def test_mismatched_root_is_skipped():
    # an SPY contract slipped into an AAPL request must be ignored entirely
    rogue = [{"option": _occ("SPY", EXPIRY, "C", 150.0),
              "open_interest": 99999, "gamma": 0.9, "delta": 0.9, "iv": 0.3}]
    out = tp.compute(_chain(extra_options=rogue), "AAPL", now=NOW)
    # n_contracts counts only the 21 strikes * 2 sides = 42 AAPL contracts
    assert out["n_contracts"] == 42


def test_symbol_normalised():
    out = tp.compute(_chain(), "  aapl ", now=NOW)
    assert out["symbol"] == "AAPL"


# --------------------------------------------------------------------------- #
# Not-found paths
# --------------------------------------------------------------------------- #

def test_empty_chain_raises_notfound():
    _raises(tp.NotFound, tp.compute,
            {"data": {"current_price": 150.0, "options": []}}, "AAPL", now=NOW)


def test_garbage_chain_raises_notfound():
    _raises(tp.NotFound, tp.compute, {"nonsense": True}, "AAPL", now=NOW)


def test_no_spot_raises_notfound():
    chain = {"data": {"options": [
        {"option": _occ("AAPL", EXPIRY, "C", 150.0),
         "open_interest": 1000, "gamma": 0.02, "delta": 0.5, "iv": 0.3}]}}
    _raises(tp.NotFound, tp.compute, chain, "AAPL", now=NOW)


# --------------------------------------------------------------------------- #
# Auto-scaled commentary engine
# --------------------------------------------------------------------------- #

def test_commentary_thresholds_autoscale():
    # gex_size bands key off m["_thresh"]; verify heavy/light language flips
    # with the threshold rather than SPY's absolute dollars.
    base = {
        "regime": "positive", "no_flip": False, "spot": 100.0,
        "zero_gamma": 95.0, "cushion": 5.0, "cushion_pct": 0.05,
        "net_gex": 50e6, "dex": 0.0, "vanna_pressure": 0.0, "charm_drift": 0.0,
        "call_wall": 105.0, "put_wall": 95.0, "call_wall_is_magnet": False,
        "oi_magnets": [], "nearest_magnet": None,
        "days_to_opex": 20, "days_since_opex": 20, "next_opex": "2026-06-19",
        "zero_dte_gamma_share": 0.1, "n_contracts": 200,
        "stale": False, "fallback_spot": False, "thin_chain": False,
    }
    heavy = tp.generate_commentary(
        {**base, "_thresh": {"GEX_HEAVY": 40e6, "GEX_MODERATE": 10e6,
                             "DEX_BAND": 1e9, "VANNA_BAND": 1e6, "CHARM_BAND": 1e6}})
    assert any("is heavy" in s for s in heavy["sentences"])
    light = tp.generate_commentary(
        {**base, "_thresh": {"GEX_HEAVY": 400e6, "GEX_MODERATE": 120e6,
                             "DEX_BAND": 1e9, "VANNA_BAND": 1e6, "CHARM_BAND": 1e6}})
    assert any("is light" in s for s in light["sentences"])


def test_determinism():
    a = tp.compute(_chain(), "AAPL", now=NOW)
    b = tp.compute(_chain(), "AAPL", now=NOW)
    assert a == b


# --------------------------------------------------------------------------- #
# Standalone runner
# --------------------------------------------------------------------------- #

def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
        except Exception as exc:  # surface, keep counting
            print(f"  FAIL {fn.__name__}: {exc}")
            continue
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} ticker-positioning tests passed.")


if __name__ == "__main__":
    _run_all()
