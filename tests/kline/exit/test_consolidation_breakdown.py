"""consolidation_breakdown exit tests."""
from __future__ import annotations

from kline.extras.consolidation_breakdown import mark

from tests.conftest import make_bars


def test_fires_when_black_k_breaks_consolidation():
    """10 bars narrow range, then black K drops below the range."""
    rows = []
    # 10 bars narrow at ~100
    for _i in range(10):
        rows.append({"open": 100, "high": 102, "low": 98, "close": 100, "volume": 1000.0})
    # Bar 10: black K dropping below 98
    rows.append({"open": 99, "high": 99.5, "low": 95, "close": 96, "volume": 1000.0})
    # Bar 11
    rows.append({"open": 96, "high": 97, "low": 94, "close": 95, "volume": 1000.0})
    df = make_bars(rows)
    out = mark(df)
    assert out.iloc[10], "Expected consolidation breakdown to fire on bar 10"


def test_does_not_fire_in_uptrend():
    """Uptrend (high range) → no consolidation."""
    rows = [{"open": 100 + i * 0.5, "high": 102 + i * 0.5, "low": 98 + i * 0.5,
             "close": 101 + i * 0.5, "volume": 1000.0} for i in range(15)]
    df = make_bars(rows)
    out = mark(df)
    assert not out.any()


def test_does_not_fire_for_green_breakdown():
    """Even if breaks below, must be black K (close < open)."""
    rows = []
    for _i in range(10):
        rows.append({"open": 100, "high": 102, "low": 98, "close": 100, "volume": 1000.0})
    # Green K: open below range low, close above open → not black
    rows.append({"open": 95, "high": 96, "low": 94, "close": 95.5, "volume": 1000.0})
    df = make_bars(rows)
    out = mark(df)
    assert not out.iloc[10]


def test_does_not_fire_when_close_stays_inside_range():
    """Black K that does not close below consolidation low → no signal."""
    rows = []
    for _i in range(10):
        rows.append({"open": 100, "high": 102, "low": 98, "close": 100, "volume": 1000.0})
    # Black K but close still above the consolidation low (98)
    rows.append({"open": 101, "high": 101.5, "low": 98.5, "close": 99, "volume": 1000.0})
    df = make_bars(rows)
    out = mark(df)
    assert not out.iloc[10]
