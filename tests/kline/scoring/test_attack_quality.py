"""Anti-course penalties (extras): base 50, deducts for volume/body/close_pos.

Audit C4 / split option B: the +25 pre_breakout_trend_days bonus was moved
to scoring/trend_continuation.py (default ON). This file tests only the
three anti-course penalties that remain in extras.
"""
from __future__ import annotations

from kline.extras.attack_quality_anti_course_penalties import score

from tests.conftest import make_bars


def test_default_score_is_50():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(2)]
    df = make_bars(rows)
    df["volume_ratio"] = [1.0, 1.0]
    df["body_pct"] = [0.01, 0.01]
    df["close_pos"] = [0.5, 0.5]
    out = score(df)
    assert (out == 50.0).all()


def test_trend_bonus_no_longer_applied_here():
    """pre_breakout_trend_days must NOT affect score in this module anymore.

    The course-aligned +25 contribution moved to scoring/trend_continuation.py.
    """
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["volume_ratio"] = [1.0]
    df["body_pct"] = [0.01]
    df["close_pos"] = [0.5]
    df["pre_breakout_trend_days"] = [17]
    assert score(df).iloc[0] == 50.0


def test_high_volume_subtracts_30():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["volume_ratio"] = [3.2]
    df["body_pct"] = [0.01]
    df["close_pos"] = [0.5]
    assert score(df).iloc[0] == 20.0


def test_score_clipped_to_zero():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["volume_ratio"] = [3.2]    # -30
    df["body_pct"] = [0.04]       # -25
    df["close_pos"] = [0.85]      # -20
    # 50 - 75 = -25 → clipped to 0
    assert score(df).iloc[0] == 0.0
