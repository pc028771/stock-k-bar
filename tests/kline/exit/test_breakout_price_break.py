"""breakout_price_break.mark: 跌破突破價（prior_high_60）→ 立即停損.

Course source: K線行進ing 紅K篇(五) 黑K接續出現.
"""
from __future__ import annotations

import pandas as pd
from kline.exit.breakout_price_break import mark

from tests.conftest import make_bars


def test_triggers_when_close_below_breakout_price():
    """Close drops below prior_high_60 captured at entry bar."""
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104, "prior_high_60": 98.0},
        {"open": 105, "high": 112, "low": 104, "close": 111, "prior_high_60": 100.0},  # entry
        # close < 100 → trigger
        {"open": 110, "high": 111, "low": 98,  "close": 99,  "prior_high_60": 100.0},
    ]
    df = make_bars(rows)
    entries = pd.Series([False, True, False])
    out = mark(df, entries)
    assert not out.iloc[0]
    assert not out.iloc[1]
    assert out.iloc[2]


def test_no_trigger_outside_early_window():
    """After BREAKOUT_PRICE_BREAK_WINDOW (2 bars) the exit is disarmed.

    Audit I8: breakout_price_break applies only to the first 2 bars after
    entry; afterwards breakout_low_break takes over.
    """
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104, "prior_high_60": 98.0},
        {"open": 105, "high": 112, "low": 104, "close": 111, "prior_high_60": 100.0},  # entry
        {"open": 110, "high": 111, "low": 105, "close": 106, "prior_high_60": 100.0},
        {"open": 105, "high": 106, "low": 102, "close": 103, "prior_high_60": 100.0},
        # bars_since_entry == 3 (outside window) and close < 100 → should NOT trigger.
        {"open": 102, "high": 103, "low": 98,  "close": 99,  "prior_high_60": 100.0},
    ]
    df = make_bars(rows)
    entries = pd.Series([False, True, False, False, False])
    out = mark(df, entries)
    assert not out.iloc[4]


def test_no_trigger_when_close_above_breakout_price():
    """Close stays above prior_high_60 — no exit."""
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104, "prior_high_60": 98.0},
        {"open": 105, "high": 112, "low": 104, "close": 111, "prior_high_60": 100.0},  # entry
        # close > 100 → no trigger
        {"open": 110, "high": 115, "low": 104, "close": 113, "prior_high_60": 100.0},
    ]
    df = make_bars(rows)
    entries = pd.Series([False, True, False])
    out = mark(df, entries)
    assert not out.iloc[2]
