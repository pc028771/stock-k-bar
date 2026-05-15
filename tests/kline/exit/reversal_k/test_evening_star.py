"""evening_star.mark: 夜星棄嬰."""
from __future__ import annotations

import pandas as pd
from kline.exit.reversal_k.evening_star import mark

from tests.conftest import make_bars


def test_evening_star_triggers():
    """K-2 red at pressure, K-1 doji, K0 long black below K-2 midpoint."""
    rows = [
        # K-2: red, open=100, close=108 → mid=104, at pressure
        {"open": 100, "high": 110, "low": 99,  "close": 108},
        # K-1: doji (open≈close)
        {"open": 109, "high": 112, "low": 107, "close": 109},
        # K0: long black (open=108, close=100 → body≈7.4%), close<mid=104
        {"open": 108, "high": 109, "low": 99,  "close": 100},
    ]
    df = make_bars(rows)
    df["overhead_supply_layer"] = pd.Series([2, 0, 0], dtype=float)
    df["is_doji"] = pd.Series([False, True, False], dtype=bool)
    out = mark(df)
    assert out.iloc[2], "Should trigger: evening star at pressure"


def test_no_pressure_on_k2_does_not_trigger():
    """Same structure but K-2 has no overhead supply."""
    rows = [
        {"open": 100, "high": 110, "low": 99,  "close": 108},
        {"open": 109, "high": 112, "low": 107, "close": 109},
        {"open": 108, "high": 109, "low": 99,  "close": 100},
    ]
    df = make_bars(rows)
    df["overhead_supply_layer"] = pd.Series([0, 0, 0], dtype=float)
    df["is_doji"] = pd.Series([False, True, False], dtype=bool)
    out = mark(df)
    assert not out.iloc[2], "Should not trigger: no pressure on K-2"


def test_k1_not_doji_does_not_trigger():
    """K-2 red at pressure but K-1 is not a doji."""
    rows = [
        {"open": 100, "high": 110, "low": 99,  "close": 108},
        {"open": 109, "high": 115, "low": 107, "close": 114},  # large red, not doji
        {"open": 108, "high": 109, "low": 99,  "close": 100},
    ]
    df = make_bars(rows)
    df["overhead_supply_layer"] = pd.Series([2, 0, 0], dtype=float)
    df["is_doji"] = pd.Series([False, False, False], dtype=bool)
    out = mark(df)
    assert not out.iloc[2], "Should not trigger: K-1 is not doji"
