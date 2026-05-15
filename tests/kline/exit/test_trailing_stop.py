"""trailing_stop.mark: 前一日低點 trailing stop.

Course source: 【買點賣點】出場點的各種依據(二) +【賣壓化解】K線圖的第一個研判要點.

> 「前一日低點當作停利點，有過昨高都算攻擊持續」
"""
from __future__ import annotations

import pandas as pd
from kline.exit.trailing_stop import mark

from tests.conftest import make_bars


def test_close_below_trailing_low_triggers():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},
        {"open": 109, "high": 112, "low": 108, "close": 111},
        {"open": 111, "high": 111, "low": 103, "close": 103},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    entries = pd.Series([False, True, False, False])
    out = mark(df, entries)
    assert out.iloc[3]


def test_close_above_trailing_low_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 110, "low": 104, "close": 109},
        {"open": 109, "high": 112, "low": 108, "close": 111},
        {"open": 111, "high": 113, "low": 109, "close": 112},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    entries = pd.Series([False, True, False, False])
    out = mark(df, entries)
    assert not out.iloc[3]
