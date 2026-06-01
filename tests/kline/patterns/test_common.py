"""Tests for patterns/_common.py — bull/bear_exhaustion_context + is_power_bar gate."""
from __future__ import annotations

import pandas as pd
import pytest

from kline.features import add_features
from kline.patterns._common import (
    bear_exhaustion_context,
    bull_exhaustion_context,
    is_power_bar,
)

from tests.conftest import make_bars


def _build_bull_exhaust_frame():
    """80 bars: rising trend with close > prior_high_60 + sunrise pattern."""
    rows = []
    for i in range(80):
        low = 100.0 + i * 1.0
        rows.append({
            "open": low + 0.2,
            "high": low + 1.5,
            "low": low,
            "close": low + 1.2,
            "volume": 1000.0,
            "ma60": 90.0,
        })
    return add_features(make_bars(rows))


def _build_breakdown_frame():
    """130 bars with progressive new-low spikes + explicitly declining MA60."""
    rows = []
    for i in range(130):
        offset = i * 0.5
        ma60 = 100.0 - offset
        if i % 20 == 0 and i > 30:
            rows.append({
                "open": 95 - offset, "high": 96 - offset,
                "low": 88 - offset, "close": 90 - offset,
                "volume": 1000.0, "ma60": ma60,
            })
        else:
            rows.append({
                "open": 95 - offset, "high": 96 - offset,
                "low": 92 - offset, "close": 94 - offset,
                "volume": 1000.0, "ma60": ma60,
            })
    return add_features(make_bars(rows))


def test_is_power_bar_raises_not_implemented():
    df = _build_bull_exhaust_frame()
    with pytest.raises(NotImplementedError):
        is_power_bar(df, "bull")


def test_bull_exhaustion_context_fires_in_rising_trend():
    df = _build_bull_exhaust_frame()
    ctx = bull_exhaustion_context(df)
    # Latter half should have a True somewhere — stock is in attack + near high
    assert ctx.iloc[60:].any(), "bull_exhaustion_context should fire during sustained rally"


def test_bull_exhaustion_context_false_in_flat_market():
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000.0, "ma60": 100.0}
        for _ in range(80)
    ]
    df = add_features(make_bars(rows))
    ctx = bull_exhaustion_context(df)
    assert not ctx.any(), "flat market should not trigger bull exhaustion"


def test_bear_exhaustion_context_fires_in_breakdown():
    df = _build_breakdown_frame()
    ctx = bear_exhaustion_context(df)
    assert ctx.iloc[80:].any(), "bear_exhaustion_context should fire during breakdown"


def test_bear_exhaustion_context_false_in_bull_trend():
    rows = [
        {"open": 100 + i * 0.3, "high": 102 + i * 0.3,
         "low": 98 + i * 0.3, "close": 101 + i * 0.3, "volume": 1000.0}
        for i in range(120)
    ]
    df = add_features(make_bars(rows))
    ctx = bear_exhaustion_context(df)
    assert not ctx.any()
