"""attack_quality.score: base 50 +/- factor adjustments, clipped [0, 100]."""
from __future__ import annotations

from kline.scoring.attack_quality import score

from tests.conftest import make_bars


def test_default_score_is_50():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(2)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [0, 0]
    df["volume_ratio"] = [1.0, 1.0]
    df["body_pct"] = [0.01, 0.01]
    df["close_pos"] = [0.5, 0.5]
    out = score(df)
    assert (out == 50.0).all()


def test_strong_trend_history_adds_25():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [17]
    df["volume_ratio"] = [1.0]
    df["body_pct"] = [0.01]
    df["close_pos"] = [0.5]
    assert score(df).iloc[0] == 75.0


def test_high_volume_subtracts_30():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [0]
    df["volume_ratio"] = [3.2]
    df["body_pct"] = [0.01]
    df["close_pos"] = [0.5]
    assert score(df).iloc[0] == 20.0


def test_score_clipped_to_zero():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["pre_breakout_trend_days"] = [0]
    df["volume_ratio"] = [3.2]    # -30
    df["body_pct"] = [0.04]       # -25
    df["close_pos"] = [0.85]      # -20
    # 50 - 75 = -25 → clipped to 0
    assert score(df).iloc[0] == 0.0
