"""dark_double_star.mark: 暗夜雙星."""
from __future__ import annotations

from kline.exit.reversal_k.dark_double_star import mark

from tests.conftest import make_bars


def test_black_k_opens_below_prev_low_with_long_body_triggers():
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104},
        {"open": 96,  "high": 97,  "low": 90,  "close": 91},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert out.iloc[1]


def test_red_k_does_not_trigger():
    rows = [
        {"open": 100, "high": 105, "low": 99, "close": 104},
        {"open": 96,  "high": 105, "low": 95, "close": 104},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert not out.iloc[1]


def test_body_below_threshold_does_not_trigger():
    rows = [
        {"open": 100, "high": 105, "low": 99, "close": 104},
        {"open": 96,  "high": 96,  "low": 94, "close": 95},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert not out.iloc[1]
