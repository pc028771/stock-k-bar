"""breakout_low_break.mark: 突破K的低點被跌破 → 攻擊假設失效.

Course source: 【單一K線】紅色誤解：連續紅K的判斷要點.
"""
from __future__ import annotations

import pandas as pd
from kline.exit.breakout_low_break import mark

from tests.conftest import make_bars


def test_close_below_entry_bar_low_triggers():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},
        {"open": 108, "high": 109, "low": 102, "close": 103},
    ]
    df = make_bars(rows)
    entries = pd.Series([False, True, False])
    out = mark(df, entries)
    assert out.iloc[2]
    assert not out.iloc[0]
    assert not out.iloc[1]


def test_close_at_or_above_entry_low_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},
        {"open": 108, "high": 109, "low": 104, "close": 105},
    ]
    df = make_bars(rows)
    entries = pd.Series([False, True, False])
    out = mark(df, entries)
    assert not out.iloc[2]


def test_per_ticker_isolation():
    rows_a = [{"open": 100, "high": 110, "low": 90, "close": 100} for _ in range(2)]
    rows_b = [{"open": 100, "high": 110, "low": 50, "close": 60} for _ in range(2)]
    df = pd.concat([
        make_bars(rows_a, ticker="A"),
        make_bars(rows_b, ticker="B"),
    ]).reset_index(drop=True)
    entries = pd.Series([True, False, True, False])
    out = mark(df, entries)
    assert not out.iloc[1]
    assert not out.iloc[3]
