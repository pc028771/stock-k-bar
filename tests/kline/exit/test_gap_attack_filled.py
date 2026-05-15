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
        # entry bar
        {"open": 100, "high": 105, "low": 99,  "close": 104, "prev_high": 95.0},
        # gap-up attack: open(115) > prev_high(104) → attack gap lower bound = 104
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
