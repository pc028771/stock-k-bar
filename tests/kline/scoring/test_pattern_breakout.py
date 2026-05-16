"""pattern_breakout scoring factor tests."""
from __future__ import annotations

from kline.scoring.pattern_breakout import score

from tests.conftest import make_bars


def test_pattern_breakout_score_positive():
    rows = [{"open": 100, "high": 102, "low": 99, "close": 100}]
    df = make_bars(rows)
    df["is_pattern_breakout"] = [True]
    assert score(df).iloc[0] == 20.0


def test_non_pattern_breakout_zero():
    rows = [{"open": 100, "high": 102, "low": 99, "close": 100}]
    df = make_bars(rows)
    df["is_pattern_breakout"] = [False]
    assert score(df).iloc[0] == 0.0
