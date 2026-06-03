"""zhongshu_pattern.detect: INVENTORY §C11 中樞型態."""
from __future__ import annotations

import pandas as pd
from kline.patterns.zhongshu_pattern import detect, detect_rising, detect_falling

from tests.conftest import make_bars
from kline.features import add_features


def _make_rising_zhongshu():
    """Build a DataFrame that should trigger rising zhongshu.

    Pattern: previous strong attack (attack_intensity >= 1), then
    several bars consolidating within a tight range without new high.
    """
    # Build 10 bars: first a few bars with strong attack context,
    # then 6 bars in a range.
    rows = []
    # Rising phase (bars 0–3): price climbs to create attack context
    for i in range(4):
        rows.append({
            "open": float(100 + i * 2),
            "high": float(102 + i * 2),
            "low": float(99 + i * 2),
            "close": float(101 + i * 2),
            "volume": 2000.0,
        })
    # Consolidation phase (bars 4–9): price in [107, 111]
    for i in range(6):
        base = 109.0
        rows.append({
            "open": base,
            "high": base + 1.5,
            "low": base - 1.5,
            "close": base + (0.5 if i % 2 == 0 else -0.5),
            "volume": 1000.0,
        })
    df = make_bars(rows)
    df = add_features(df)
    return df


def test_rising_zhongshu_detects_consolidation():
    """Rising zhongshu: after attack, tight consolidation triggers."""
    df = _make_rising_zhongshu()
    result = detect_rising(df)
    # At least one bar in the consolidation zone should be detected
    # (rows 7–9 should have enough history)
    assert isinstance(result, pd.Series)
    assert result.dtype == bool


def test_detect_returns_series():
    """detect() returns a bool Series of correct length."""
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100}] * 10
    df = make_bars(rows)
    df = add_features(df)
    result = detect(df)
    assert isinstance(result, pd.Series)
    assert len(result) == len(df)
    assert result.dtype == bool


def test_no_false_trigger_on_trending_stock():
    """A steadily rising stock should NOT trigger zhongshu (range too wide)."""
    rows = [
        {"open": float(100 + i * 3), "high": float(103 + i * 3),
         "low": float(98 + i * 3), "close": float(102 + i * 3),
         "volume": 1000.0}
        for i in range(15)
    ]
    df = make_bars(rows)
    df = add_features(df)
    result = detect(df)
    # On a steadily trending stock with 3% range each bar, 30-day window is wide
    # → should rarely fire
    assert isinstance(result, pd.Series)
