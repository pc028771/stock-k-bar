"""prev_day_low_break.mark: 前一日低點跌破 (short-term exit).

Course source: 【買點賣點】買點與攻擊研判.
"""
from __future__ import annotations

from kline.exit.prev_day_low_break import mark

from tests.conftest import make_bars


def test_close_below_prev_low_triggers():
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 100},
        {"open": 100, "high": 103, "low": 98, "close": 98},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert out.iloc[1]


def test_close_at_prev_low_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 100},
        {"open": 100, "high": 103, "low": 99, "close": 99},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert not out.iloc[1]
