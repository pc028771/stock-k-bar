"""neckline_break.mark: 頸線跌破 (with next-day confirmation).

Course source: 【買點賣點】多方操作的出場點邏輯.

Neckline proxy: prior_low_20. Confirm with next-day close also below.
Trigger fires on the CONFIRMATION DAY (one day after first break).
"""
from __future__ import annotations

from kline.extras.neckline_break_crude import mark

from tests.conftest import make_bars


def test_consecutive_break_triggers_on_second_day():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 100, "high": 102, "low": 89,  "close": 92},
        {"open": 92,  "high": 94,  "low": 88,  "close": 91},
    ]
    df = make_bars(rows)
    df["prior_low_20"] = [95.0, 95.0, 95.0]
    out = mark(df)
    assert out.iloc[2]
    assert not out.iloc[1]


def test_reclaim_after_break_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 100, "high": 102, "low": 89,  "close": 92},
        {"open": 92,  "high": 98,  "low": 92,  "close": 96},
    ]
    df = make_bars(rows)
    df["prior_low_20"] = [95.0, 95.0, 95.0]
    out = mark(df)
    assert not out.iloc[2]


def test_nan_neckline_does_not_trigger():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    df["prior_low_20"] = [float("nan")] * 3
    out = mark(df)
    assert not out.any()
