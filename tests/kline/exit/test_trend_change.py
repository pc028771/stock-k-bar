"""trend_change.mark: 趨勢改變型 → MA60 由上升轉下彎.

Course source: 【買點賣點】出場點的各種依據(一).

Course says: take the highest of (末升低, 上升趨勢線, MA60 下彎).
Intro doesn't give precise detection for 末升低 / 趨勢線; this implementation
covers MA60 turn-down only, with placeholders for the other two.
"""
from __future__ import annotations

from kline.exit.trend_change import mark

from tests.conftest import make_bars


def test_ma60_slope_flip_negative_triggers():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    df["ma60_slope_5d"] = [0.01, 0.005, -0.002]
    out = mark(df)
    assert out.iloc[2]
    assert not out.iloc[0]
    assert not out.iloc[1]


def test_continuous_negative_slope_does_not_re_trigger():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    df["ma60_slope_5d"] = [-0.001, -0.002, -0.003]
    out = mark(df)
    assert not out.any()


def test_nan_slope_does_not_trigger():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    df["ma60_slope_5d"] = [float("nan"), float("nan"), -0.01]
    out = mark(df)
    assert not out.any()
