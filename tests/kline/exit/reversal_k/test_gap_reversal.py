"""gap_reversal.mark: 跳空反轉."""
from __future__ import annotations

import pandas as pd
from kline.exit.reversal_k.gap_reversal import mark

from tests.conftest import make_bars


def test_long_red_then_black_then_gap_down_triggers():
    """K-2 long red, K-1 black closing below K-2, K0 gaps down."""
    rows = [
        # K-2: long red (open=100, close=105 → 5% body)
        {"open": 100, "high": 106, "low": 99,  "close": 105},
        # K-1: black, close=102 < K-2 close=105
        {"open": 105, "high": 106, "low": 100, "close": 102},
        # K0: gap-down (open=99 < K-1.low=100)
        {"open": 99,  "high": 100, "low": 96,  "close": 97},
    ]
    df = make_bars(rows)
    df["prior_high_60"] = pd.Series([99.0, 99.0, 99.0], dtype=float)
    out = mark(df)
    assert out.iloc[2], "Should trigger: long red + black + gap-down"


def test_new_high_red_triggers():
    """K-2 is a new high red (even if not a long body), K-1 black, K0 gap-down."""
    rows = [
        # K-2: small red but at new high (high=106 >= prior_high_60=106)
        {"open": 100, "high": 106, "low": 99,  "close": 101},
        # K-1: black, close=100 < K-2 close=101; low=100
        {"open": 101, "high": 103, "low": 100, "close": 100},
        # K0: gap-down open=98 < K-1.low=100
        {"open": 98,  "high": 99,  "low": 95,  "close": 96},
    ]
    df = make_bars(rows)
    # K-2 high=106 >= prior_high_60=106 → qualifies as new-high red
    df["prior_high_60"] = pd.Series([106.0, 106.0, 106.0], dtype=float)
    out = mark(df)
    assert out.iloc[2], "Should trigger: new-high red qualifies as K-2"


def test_k0_no_gap_down_does_not_trigger():
    """All conditions met except K0 does not gap down."""
    rows = [
        {"open": 100, "high": 106, "low": 99,  "close": 105},
        {"open": 105, "high": 106, "low": 100, "close": 102},
        # K0: open=101 > K-1.low=100 — not a gap-down
        {"open": 101, "high": 102, "low": 98,  "close": 99},
    ]
    df = make_bars(rows)
    df["prior_high_60"] = pd.Series([99.0, 99.0, 99.0], dtype=float)
    out = mark(df)
    assert not out.iloc[2], "Should not trigger: no gap-down"


def test_k1_red_does_not_trigger():
    """K-1 is red, not black."""
    rows = [
        {"open": 100, "high": 106, "low": 99,  "close": 105},
        {"open": 100, "high": 108, "low": 99,  "close": 107},  # red
        {"open": 99,  "high": 100, "low": 96,  "close": 97},
    ]
    df = make_bars(rows)
    df["prior_high_60"] = pd.Series([99.0, 99.0, 99.0], dtype=float)
    out = mark(df)
    assert not out.iloc[2], "Should not trigger: K-1 is red"
