"""bearish_engulfing.mark: 空頭吞噬."""
from __future__ import annotations

from kline.exit.reversal_k.bearish_engulfing import mark

from tests.conftest import make_bars


def test_black_k_fully_engulfs_prior_red_triggers():
    """K-1 red, K0 black whose body fully covers K-1's body."""
    rows = [
        {"open": 100, "high": 106, "low": 99,  "close": 105},  # K-1: red, body 100→105
        {"open": 106, "high": 107, "low": 96,  "close": 98},   # K0: black, open>=105, close<=100
    ]
    df = make_bars(rows)
    out = mark(df)
    assert out.iloc[1], "Should trigger: black engulfs prior red"


def test_partial_engulf_does_not_trigger():
    """K0 black but close is only partially inside K-1 body (close > K-1.open)."""
    rows = [
        {"open": 100, "high": 106, "low": 99,  "close": 105},  # K-1: red
        {"open": 106, "high": 107, "low": 102, "close": 103},  # K0: black, close=103 > K-1.open=100
    ]
    df = make_bars(rows)
    out = mark(df)
    assert not out.iloc[1], "Should not trigger: does not fully engulf"


def test_red_k_today_does_not_trigger():
    """K0 is red, not black."""
    rows = [
        {"open": 100, "high": 106, "low": 99,  "close": 105},
        {"open": 106, "high": 110, "low": 97,  "close": 109},  # red
    ]
    df = make_bars(rows)
    out = mark(df)
    assert not out.iloc[1], "Should not trigger: today is red"
