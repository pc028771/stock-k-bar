"""prev_day_low_break.mark: 前一日低點跌破 (short-term exit).

Course source: 【買點賣點】買點與攻擊研判 + 紅K篇(二).

Course-required gate: previous bar must have had 攻擊意義 (red K at new
60-day high, upper-shadow K at new high, or doji follow-up after a red
attack K). Without the gate, the rule degenerates into a mechanical
prior-low stop that the course does NOT teach.
"""
from __future__ import annotations

from kline.exit.prev_day_low_break import mark

from tests.conftest import make_bars


def test_close_below_prev_low_with_attack_meaning_triggers():
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 100},
        {"open": 100, "high": 103, "low": 98, "close": 98},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    df["prev_bar_had_attack_meaning"] = [False, True]
    out = mark(df)
    assert out.iloc[1]


def test_close_below_prev_low_without_attack_meaning_does_not_trigger():
    """Course requires prev bar to have 攻擊意義 — without it, no fire."""
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 100},
        {"open": 100, "high": 103, "low": 98, "close": 98},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    df["prev_bar_had_attack_meaning"] = [False, False]
    out = mark(df)
    assert not out.iloc[1]


def test_close_at_prev_low_does_not_trigger():
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 100},
        {"open": 100, "high": 103, "low": 99, "close": 99},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    df["prev_bar_had_attack_meaning"] = [False, True]
    out = mark(df)
    assert not out.iloc[1]


def test_missing_gate_column_does_not_fire():
    """Conservative behavior: without the gate column, never fire."""
    rows = [
        {"open": 100, "high": 102, "low": 99, "close": 100},
        {"open": 100, "high": 103, "low": 98, "close": 98},
    ]
    df = make_bars(rows)
    df["prev_low"] = df["low"].shift(1)
    out = mark(df)
    assert not out.any()
