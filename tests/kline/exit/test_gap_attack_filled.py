"""gap_attack_filled.mark: 攻擊跳空被消除 → 出場.

Course source: K線行進ing 跳空篇(二) 一般跳空的行進判斷.
"""
from __future__ import annotations

import pandas as pd
from kline.exit.gap_attack_filled import mark

from tests.conftest import make_bars


def test_triggers_when_close_falls_below_attack_gap_lower_bound():
    """After a gap-up attack, close drops below its lower bound (prev_high)."""
    rows = [
        # entry bar — NOT a gap-up (open == prev_high)
        {"open": 100, "high": 105, "low": 99,  "close": 104, "prev_high": 100.0},
        # FIRST gap-up attack: open(115) > prev_high(104) → locked at 104
        {"open": 115, "high": 120, "low": 113, "close": 118, "prev_high": 104.0},
        # close drops below 104 → gap killed
        {"open": 110, "high": 111, "low": 100, "close": 102, "prev_high": 118.0},
    ]
    df = make_bars(rows)
    entries = pd.Series([True, False, False])
    out = mark(df, entries)
    assert not out.iloc[0]
    assert not out.iloc[1]
    assert out.iloc[2]


def test_first_attack_gap_locks_not_replaced_by_later_smaller_gap():
    """Audit C5: course says the FIRST attack gap is canonical.

    Once locked at trade entry, later gap-ups must NOT raise the reference.
    """
    rows = [
        # entry bar — NOT a gap-up (open == prev_high so no gap)
        {"open": 100, "high": 105, "low": 99,  "close": 104, "prev_high": 100.0},
        # FIRST gap-up attack: prev_high=104 → locked reference
        {"open": 115, "high": 120, "low": 113, "close": 118, "prev_high": 104.0},
        # ordinary up day, no gap
        {"open": 118, "high": 122, "low": 117, "close": 121, "prev_high": 120.0},
        # SECOND (later) gap-up: prev_high=122 — must NOT replace 104
        {"open": 125, "high": 128, "low": 124, "close": 127, "prev_high": 122.0},
        # close 106: above 104 (original locked) but below 122 (most recent)
        # → must NOT fire (course-correct behavior)
        {"open": 120, "high": 121, "low": 105, "close": 106, "prev_high": 128.0},
    ]
    df = make_bars(rows)
    entries = pd.Series([True, False, False, False, False])
    out = mark(df, entries)
    assert not out.iloc[4], "Must not fire when only the later (non-original) gap is broken"


def test_first_attack_gap_kill_fires():
    """Original (first) attack gap broken → fires."""
    rows = [
        {"open": 100, "high": 105, "low": 99,  "close": 104, "prev_high": 100.0},
        # FIRST gap-up: prev_high=104 locked
        {"open": 115, "high": 120, "low": 113, "close": 118, "prev_high": 104.0},
        # close drops below 104 → fires
        {"open": 110, "high": 111, "low": 100, "close": 102, "prev_high": 118.0},
    ]
    df = make_bars(rows)
    entries = pd.Series([True, False, False])
    out = mark(df, entries)
    assert out.iloc[2]


def test_no_trigger_before_any_attack_gap_exists():
    """Without a gap-up after entry, the condition never fires."""
    rows = [
        # entry bar (no gap-up: open 100 is not > prev_high 95)
        {"open": 100, "high": 105, "low": 99,  "close": 104, "prev_high": 95.0},
        # ordinary up day — no gap-up
        {"open": 104, "high": 108, "low": 103, "close": 107, "prev_high": 104.0},
        # close drops, but no attack gap was ever set
        {"open": 107, "high": 108, "low": 96,  "close": 97,  "prev_high": 107.0},
    ]
    df = make_bars(rows)
    entries = pd.Series([True, False, False])
    out = mark(df, entries)
    assert not out.any()
