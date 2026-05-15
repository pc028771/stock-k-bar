"""two_crows.mark: 雙鴉躍空."""
from __future__ import annotations

import pandas as pd
from kline.exit.reversal_k.two_crows import mark

from tests.conftest import make_bars


def test_two_crows_triggers():
    """K-3 base, K-2 gap-up black at pressure, K-1 small black, K0 gap-down open."""
    rows = [
        # K-3: base bar, high=105
        {"open": 100, "high": 105, "low": 98,  "close": 104},
        # K-2: gap-up (open=107>K-3.high=105), black, at pressure
        {"open": 107, "high": 110, "low": 105, "close": 106},
        # K-1: small black (open=106, close=105.5 → ~0.5% body)
        {"open": 106, "high": 106.5, "low": 105, "close": 105.5},
        # K0: gap-down open (open=104 < K-1.low=105)
        {"open": 104, "high": 104.5, "low": 102, "close": 103},
    ]
    df = make_bars(rows)
    df["overhead_supply_layer"] = pd.Series([0, 2, 0, 0], dtype=float)
    out = mark(df)
    assert out.iloc[3], "Should trigger: two crows with gap-down"


def test_k2_no_gap_up_does_not_trigger():
    """K-2 does not gap up above K-3 high."""
    rows = [
        {"open": 100, "high": 105, "low": 98,  "close": 104},
        # K-2: open=104 < K-3 high=105, so no gap-up
        {"open": 104, "high": 108, "low": 103, "close": 105},
        {"open": 105, "high": 105.5, "low": 104, "close": 104.5},
        {"open": 103, "high": 103.5, "low": 101, "close": 102},
    ]
    df = make_bars(rows)
    df["overhead_supply_layer"] = pd.Series([0, 2, 0, 0], dtype=float)
    out = mark(df)
    assert not out.iloc[3], "Should not trigger: K-2 did not gap up"


def test_k0_no_gap_down_does_not_trigger():
    """K0 open is above K-1 low — no gap-down."""
    rows = [
        {"open": 100, "high": 105, "low": 98,  "close": 104},
        {"open": 107, "high": 110, "low": 105, "close": 106},
        {"open": 106, "high": 106.5, "low": 104, "close": 105},
        # K0: open=105 = K-1.low=104 boundary — open is NOT < K-1.low
        {"open": 105, "high": 105.5, "low": 103, "close": 104},
    ]
    df = make_bars(rows)
    df["overhead_supply_layer"] = pd.Series([0, 2, 0, 0], dtype=float)
    out = mark(df)
    assert not out.iloc[3], "Should not trigger: no gap-down on K0"
