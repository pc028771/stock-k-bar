"""breakout.detect: close > prior_high_60 AND close > ma60.

Course source: 【突破跌破】突破意義的釐清; volume / red K / close_pos NOT required.
"""
from __future__ import annotations

from kline.entry.breakout import detect
from kline.features import add_features

from tests.conftest import make_bars


def _bars_with_breakout_at(idx: int, n: int = 65):
    """65 ascending bars; force a breakout at `idx` by spiking close."""
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 1000.0, "ma60": 100.0} for _ in range(n)]
    rows[idx]["close"] = 110.0
    rows[idx]["high"] = 111.0
    return make_bars(rows)


def test_breakout_triggers_when_close_above_prior_high_60():
    df = add_features(_bars_with_breakout_at(60))
    signal = detect(df)
    assert signal.iloc[60]
    assert not signal.iloc[59]


def test_breakout_does_not_require_red_k():
    # Force a black K that still breaks above prior_high_60.
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 1000.0, "ma60": 100.0} for _ in range(65)]
    rows[60]["open"] = 115.0
    rows[60]["high"] = 116.0
    rows[60]["low"] = 109.0
    rows[60]["close"] = 110.0  # black K, but close > prior_high_60 (101)
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert signal.iloc[60]  # Triggers — course says color irrelevant


def test_breakout_excluded_if_in_breakdown_pattern():
    """
    Even if close > prior_high_60 AND > ma60, 破底型態 stocks must be excluded.
    """
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 1000.0, "ma60": 100.0} for _ in range(65)]
    rows[60]["close"] = 110.0
    rows[60]["high"] = 111.0
    df = add_features(make_bars(rows))

    # Force the breakdown flag on for the target bar
    df.loc[60, "is_in_breakdown_pattern"] = True

    signal = detect(df)
    assert not signal.iloc[60], "Breakdown-pattern stock must be excluded from breakout entry"


def test_breakout_blocked_when_below_ma60():
    rows = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "volume": 1000.0, "ma60": 120.0} for _ in range(65)]
    rows[60]["close"] = 110.0
    rows[60]["high"] = 111.0
    df = add_features(make_bars(rows))
    signal = detect(df)
    assert not signal.iloc[60]
