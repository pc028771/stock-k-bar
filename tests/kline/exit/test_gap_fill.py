"""gap_fill.mark: 攻擊跳空回補.

Course source: 【買點賣點】出場點的各種依據(二).

Trigger: (stock_gap - market_gap) >= 2% AND close < prev_close.
"""
from __future__ import annotations

from kline.exit.gap_fill import mark

from tests.conftest import make_bars


def _df_with_market_col(rows, market_open_rets):
    df = make_bars(rows)
    df["prev_close"] = df["close"].shift(1)
    df["market_open_ret"] = market_open_rets
    return df


def test_excess_gap_with_close_below_prev_close_triggers():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 106, "low": 99,  "close": 99},
    ]
    df = _df_with_market_col(rows, market_open_rets=[0.0, 0.005])
    out = mark(df)
    assert out.iloc[1]
    assert not out.iloc[0]


def test_no_trigger_when_market_gap_explains_stock_gap():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 106, "low": 99,  "close": 99},
    ]
    df = _df_with_market_col(rows, market_open_rets=[0.0, 0.05])
    out = mark(df)
    assert not out.iloc[1]


def test_no_trigger_when_close_not_below_prev_close():
    rows = [
        {"open": 100, "high": 102, "low": 99,  "close": 100},
        {"open": 105, "high": 106, "low": 99,  "close": 101},
    ]
    df = _df_with_market_col(rows, market_open_rets=[0.0, 0.0])
    out = mark(df)
    assert not out.iloc[1]
