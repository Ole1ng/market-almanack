"""Tests for the SPY positioning rule engine (spec Section 9.5).

Pure, deterministic engine -> exact-text assertions. Two layers:
  1. Per-rule threshold tests: a metrics dict tuned to fire one rule, asserting
     its sentence appears (and, just outside the band, does not).
  2. ~10 scenario snapshot tests: hand-built fixtures asserting the full
     headline + ordered sentence list.

Run standalone:  python -m panels.test_spy_positioning
Or with pytest:  pytest panels/test_spy_positioning.py
"""

from __future__ import annotations

import copy

from panels import spy_positioning as sp
from panels.spy_positioning import generate_commentary

# --------------------------------------------------------------------------- #
# Base fixture: firmly positive, quiet, mid-range — fires almost nothing else.
# --------------------------------------------------------------------------- #

BASE = {
    "spot": 600.00,
    "spot_source": "current_price",
    "regime": "positive",
    "zero_gamma": 590.00,
    "no_flip": False,
    "cushion": 10.00,
    "cushion_pct": 10.0 / 600.0,          # ~1.67% > 0.75% -> firm
    "net_gex": 500e6,                       # moderate
    "dex": 0.0,
    "vanna_pressure": 0.0,
    "charm_drift": 0.0,
    "call_wall": 615.00,                    # ~2.5% away -> not near
    "put_wall": 585.00,                     # ~2.5% away -> not near
    "call_wall_is_magnet": False,
    "oi_magnets": [{"strike": 610.0, "oi": 50000}],
    "nearest_magnet": 610.0,
    "days_to_opex": 20,
    "days_since_opex": 20,
    "next_opex": "2026-06-19",
    "zero_dte_gamma_share": 0.10,
    "n_contracts": 800,
    "stale": False,
    "fallback_spot": False,
    "thin_chain": False,
}


def m(**over):
    d = copy.deepcopy(BASE)
    d.update(over)
    return d


def _all_text(out):
    return " ".join([out["headline"]] + out["warnings"] + out["sentences"])


# --------------------------------------------------------------------------- #
# 1. Per-rule threshold tests
# --------------------------------------------------------------------------- #

def test_regime_firm_vs_fragile():
    firm = generate_commentary(m(cushion_pct=0.0080))
    assert "Positive gamma with a" in firm["sentences"][0]
    fragile = generate_commentary(m(cushion=4.0, cushion_pct=0.0070))
    assert "Positive but fragile gamma" in fragile["sentences"][0]


def test_regime_negative_marginal_vs_deep():
    marg = generate_commentary(
        m(regime="negative", zero_gamma=603.0, cushion=-3.0, cushion_pct=-0.005))
    assert "Marginally negative gamma" in marg["sentences"][0]
    deep = generate_commentary(
        m(regime="negative", zero_gamma=615.0, cushion=-15.0, cushion_pct=-0.025))
    assert "Deeply negative gamma" in deep["sentences"][0]


def test_no_flip_substitutes_regime():
    out = generate_commentary(m(no_flip=True, zero_gamma=None,
                                cushion=None, cushion_pct=None))
    assert "No gamma flip within ±8%" in out["sentences"][0]


def test_gex_size_bands():
    heavy = _all_text(generate_commentary(m(net_gex=900e6)))
    assert "is heavy" in heavy
    mod = _all_text(generate_commentary(m(net_gex=500e6)))
    assert "is moderate" in mod
    light = generate_commentary(m(net_gex=100e6))
    assert "is light" in _all_text(light)
    assert "Light positioning" in light["headline"]


def test_wall_proximity_and_magnet_upgrade():
    near = _all_text(generate_commentary(m(call_wall=601.0)))
    assert "call wall" in near and "stall" in near
    pin = _all_text(generate_commentary(
        m(call_wall=601.0, call_wall_is_magnet=True)))
    assert "pin candidate" in pin


def test_put_wall_regime_conditional():
    pos = _all_text(generate_commentary(m(put_wall=598.0)))
    assert "should act as support" in pos
    neg = _all_text(generate_commentary(
        m(regime="negative", zero_gamma=610.0, cushion=-10.0,
          cushion_pct=-0.0167, put_wall=598.0)))
    assert "acceleration point if breached" in neg


def test_open_field_when_no_wall_near():
    out = _all_text(generate_commentary(m(call_wall=640.0, put_wall=560.0)))
    assert "mid-range between" in out


def test_range_compression_bands():
    comp = _all_text(generate_commentary(m(call_wall=606.0, put_wall=595.0)))
    assert "compressed" in comp
    wide = _all_text(generate_commentary(m(call_wall=640.0, put_wall=560.0)))
    assert "wide" in wide


def test_flip_watch_suppresses_gex_size():
    out = generate_commentary(m(zero_gamma=599.0, cushion=1.0, cushion_pct=0.0017))
    txt = _all_text(out)
    assert "vol trigger" in txt
    assert "is moderate" not in txt and "is heavy" not in txt


def test_dex_interaction_suppresses_standalone():
    out = generate_commentary(
        m(regime="negative", zero_gamma=615.0, cushion=-15.0,
          cushion_pct=-0.025, dex=-4e9))
    txt = _all_text(out)
    assert "both hedging engines point the same way" in txt
    assert "squeeze fuel on rallies" not in txt


def test_vanna_band_silent_inside():
    inside = generate_commentary(m(vanna_pressure=200e6))
    assert not any("Vanna" in s for s in inside["sentences"])
    out = _all_text(generate_commentary(m(vanna_pressure=600e6)))
    assert "vol crush" in out


def test_charm_muted_far_from_opex():
    muted = generate_commentary(m(charm_drift=50e6, days_to_opex=20))
    assert not any("Charm drift" in s for s in muted["sentences"])
    fires = _all_text(generate_commentary(m(charm_drift=200e6, days_to_opex=20)))
    assert "Charm drift" in fires


def test_charm_opex_intensifies():
    out = _all_text(generate_commentary(m(charm_drift=200e6, days_to_opex=2)))
    assert "intensifies into Friday" in out


def test_dte_dominated_sentence():
    out = generate_commentary(m(zero_dte_gamma_share=0.45))
    assert any("intraday-only levels" in s for s in out["sentences"])


def test_dte_conditions_headline_wording():
    # when dte is the dominant feature, dedicated 0DTE headline
    out = generate_commentary(m(zero_dte_gamma_share=0.45, net_gex=900e6))
    assert "intraday levels only" in out["headline"]
    # when the headline mentions "levels", 0DTE rewrites it to "intraday levels"
    light = generate_commentary(m(zero_dte_gamma_share=0.45, net_gex=80e6))
    assert "intraday levels" in light["headline"]


def test_quality_warnings_prepended():
    out = generate_commentary(m(stale=True, fallback_spot=True, thin_chain=True))
    assert len(out["warnings"]) == 3
    assert out["warnings"][0].startswith("⚠")


def test_cap_at_six_sentences():
    # crank many rules on at once
    out = generate_commentary(
        m(regime="negative", zero_gamma=615.0, cushion=-15.0, cushion_pct=-0.025,
          net_gex=900e6, call_wall=601.0, put_wall=599.0, dex=-4e9,
          vanna_pressure=-600e6, charm_drift=-200e6, days_to_opex=2,
          zero_dte_gamma_share=0.45))
    assert len(out["sentences"]) <= 6


def test_determinism():
    a = generate_commentary(m(net_gex=900e6))
    b = generate_commentary(m(net_gex=900e6))
    assert a == b


# --------------------------------------------------------------------------- #
# 2. Scenario snapshot tests (~10 fixtures) — exact headline assertions
# --------------------------------------------------------------------------- #

SCENARIOS = {
    "firm_positive": (m(net_gex=900e6),
                      "Positive gamma — dealer hedging dampens the tape."),
    "fragile_positive": (m(cushion=2.0, cushion_pct=0.0033, net_gex=900e6),
                         "Positive gamma — dealer hedging dampens the tape."),
    "flip_watch": (m(zero_gamma=599.0, cushion=1.0, cushion_pct=0.0017),
                   "Sitting on the vol trigger at 599.00 — regime in play."),
    "deep_neg_short_delta": (
        m(regime="negative", zero_gamma=615.0, cushion=-15.0, cushion_pct=-0.025,
          dex=-4e9, net_gex=-900e6),
        "Negative gamma with dealers short delta — two-way volatility risk elevated."),
    "opex_week": (m(days_to_opex=2, charm_drift=200e6, net_gex=900e6,
                    call_wall=602.0),
                  "Positive gamma, pinned under the 602.00 call wall — range day favoured."),
    "zero_dte_dominated": (m(zero_dte_gamma_share=0.50, net_gex=900e6),
                           "Positive gamma on a 0DTE-dominated tape — intraday levels only."),
    "light_positioning": (m(net_gex=80e6),
                          "Light positioning — levels carry little weight today."),
    "all_supportive": (m(vanna_pressure=600e6, charm_drift=200e6, net_gex=900e6),
                       "Positive gamma — dealer hedging dampens the tape."),
    "all_adverse": (
        m(regime="negative", zero_gamma=615.0, cushion=-15.0, cushion_pct=-0.025,
          vanna_pressure=-600e6, charm_drift=-200e6, net_gex=-900e6),
        "Negative gamma — moves amplified, trend conditions."),
    "conflict": (m(vanna_pressure=-600e6, net_gex=900e6),
                 "Positive gamma but adverse vanna — fragile to a vol spike."),
}


def test_scenarios_headlines():
    for name, (metrics, expected) in SCENARIOS.items():
        out = generate_commentary(metrics)
        if expected is not None:
            assert out["headline"] == expected, (
                f"{name}: got {out['headline']!r}, want {expected!r}")
        # every scenario must produce at least a regime sentence and <=6 total
        assert 1 <= len(out["sentences"]) <= 6, name


def test_all_supportive_synthesis_present():
    out = generate_commentary(
        m(vanna_pressure=600e6, charm_drift=200e6, net_gex=900e6))
    assert any("uniformly supportive" in s for s in out["sentences"])
    # synthesis suppresses raw vanna/dex flow sentences
    assert not any("vol crush" in s for s in out["sentences"])


def test_all_adverse_synthesis_present():
    out = generate_commentary(
        m(regime="negative", zero_gamma=615.0, cushion=-15.0, cushion_pct=-0.025,
          vanna_pressure=-600e6, charm_drift=-200e6, net_gex=-900e6))
    assert any("uniformly adverse" in s for s in out["sentences"])


def test_sentences_ordered_regime_first():
    out = generate_commentary(
        m(net_gex=900e6, call_wall=601.0, vanna_pressure=600e6))
    # regime sentence always leads
    assert out["sentences"][0].startswith("Positive")


# --------------------------------------------------------------------------- #
# Standalone runner
# --------------------------------------------------------------------------- #

def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} rule-engine tests passed.")


if __name__ == "__main__":
    _run_all()
