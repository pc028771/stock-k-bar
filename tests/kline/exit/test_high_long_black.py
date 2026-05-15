"""high_long_black.mark: 高檔長黑 → 獲利了結賣壓訊號.

Course source: K線行進ing 黑K篇(二) 高檔長黑 + 事件(九) 壓力現象.
"""
from __future__ import annotations

import pandas as pd
from kline.exit.high_long_black import mark

from tests.conftest import make_bars


def _make_high_zone_df(final_open: float, final_close: float) -> pd.DataFrame:
    """Build a 62-bar DataFrame where the first 60 bars create a high-zone range,
    then bar 61 is the signal bar with specified open/close.
    """
    # 60 prior bars: low=50, high=70 → ratio = 70/50 = 1.4 >= HIGH_ZONE_RANGE_MIN (1.3)
    rows = []
    for _i in range(60):
        rows.append({"open": 60, "high": 70, "low": 50, "close": 65})
    # bar 60: neutral (will be "yesterday" for rolling shift)
    rows.append({"open": 65, "high": 66, "low": 64, "close": 65})
    # bar 61: signal bar
    rows.append({
        "open": final_open, "high": final_open + 1,
        "low": final_close - 1, "close": final_close,
    })
    return make_bars(rows)


def test_triggers_in_high_zone_with_long_black():
    """In a high-zone context, a long black K (>= 4% body) fires the exit."""
    # open=100, close=95 → body_pct = 5/100 = 5% >= 4%
    df = _make_high_zone_df(final_open=100.0, final_close=95.0)
    out = mark(df)
    assert out.iloc[-1], "Expected exit signal on final long-black bar in high zone"
    assert not out.iloc[0], "Should not fire on early bars lacking 60-bar history"


def test_no_trigger_when_body_is_small():
    """A small black K in high zone does not trigger (body < 4%)."""
    # open=100, close=99 → body_pct = 1/100 = 1% < 4%
    df = _make_high_zone_df(final_open=100.0, final_close=99.5)
    out = mark(df)
    assert not out.iloc[-1], "Small body should not trigger high_long_black"


def test_no_trigger_in_flat_zone_with_long_black():
    """Even with a long black K, no trigger when range expansion is insufficient."""
    # Build 62 bars with narrow range: high=51, low=50 → ratio = 1.02 < 1.3
    rows = []
    for _i in range(60):
        rows.append({"open": 50, "high": 51, "low": 49, "close": 50})
    rows.append({"open": 50, "high": 51, "low": 49, "close": 50})
    # long black but flat zone
    rows.append({"open": 50, "high": 51, "low": 44, "close": 47})
    df = make_bars(rows)
    out = mark(df)
    assert not out.iloc[-1], "Flat zone should not trigger high_long_black"
