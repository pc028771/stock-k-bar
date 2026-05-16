"""trend_continuation.score: +25 when pre_breakout_trend_days >= 17, else 0.

Audit C4 split option B: the course-aligned half of legacy attack_quality.
"""
from __future__ import annotations

from kline.scoring.trend_continuation import score

from tests.conftest import make_bars


def test_below_threshold_returns_zero():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [16]
    assert score(df).iloc[0] == 0.0


def test_at_threshold_returns_25():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [17]
    assert score(df).iloc[0] == 25.0


def test_above_threshold_returns_25():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [20]
    assert score(df).iloc[0] == 25.0
