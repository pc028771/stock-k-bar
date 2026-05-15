"""sunrise_attack_end.mark: 日出攻擊結束 → 出場.

Course source: K線行進ing 紅K篇(七) 日出攻擊 + 事件(十) 操作的開始與結束.
"""
from __future__ import annotations

from kline.exit.sunrise_attack_end import mark

from tests.conftest import make_bars


def test_triggers_when_sunrise_streak_breaks():
    """After MIN_SUNRISE_BARS consecutive sunrise bars, a non-sunrise fires exit."""
    # Sunrise: high > prev_high AND low > prev_low
    rows = [
        # bar 0: non-sunrise baseline
        {"open": 100, "high": 105, "low": 99,  "close": 104, "prev_high": 106.0, "prev_low": 98.0},
        # bar 1: sunrise (high 110 > prev_high 105, low 103 > prev_low 99)
        {"open": 104, "high": 110, "low": 103, "close": 109, "prev_high": 105.0, "prev_low": 99.0},
        # bar 2: sunrise (high 115 > prev_high 110, low 107 > prev_low 103)
        {"open": 109, "high": 115, "low": 107, "close": 114, "prev_high": 110.0, "prev_low": 103.0},
        # bar 3: non-sunrise (low 106 NOT > prev_low 107) → streak of 2 broken → trigger
        {"open": 114, "high": 116, "low": 106, "close": 110, "prev_high": 115.0, "prev_low": 107.0},
    ]
    df = make_bars(rows)
    out = mark(df)
    assert not out.iloc[0]
    assert not out.iloc[1]
    assert not out.iloc[2]
    assert out.iloc[3]


def test_no_trigger_without_prior_streak():
    """A lone non-sunrise day with no prior streak does not fire."""
    rows = [
        # bar 0: non-sunrise
        {"open": 100, "high": 105, "low": 99,  "close": 104, "prev_high": 106.0, "prev_low": 98.0},
        # bar 1: non-sunrise again (no streak built up)
        {"open": 104, "high": 108, "low": 98,  "close": 106, "prev_high": 105.0, "prev_low": 99.0},
        # bar 2: non-sunrise (still no streak)
        {"open": 106, "high": 109, "low": 97,  "close": 105, "prev_high": 108.0, "prev_low": 98.0},
    ]
    df = make_bars(rows)
    out = mark(df)
    assert not out.any()
