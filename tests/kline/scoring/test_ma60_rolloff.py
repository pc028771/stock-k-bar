"""ma60_rolloff.score: penalty when upcoming MA60 carry-off is bullish."""
from __future__ import annotations

from kline.scoring.ma60_rolloff import score

from tests.conftest import make_bars


def test_rolloff_close_above_current_close_is_penalty():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["ma60_rolling_off_close"] = [110.0]
    out = score(df)
    assert out.iloc[0] < 0


def test_rolloff_close_below_current_close_is_bonus():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["ma60_rolling_off_close"] = [90.0]
    out = score(df)
    assert out.iloc[0] > 0


def test_nan_rolloff_returns_zero():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["ma60_rolling_off_close"] = [float("nan")]
    out = score(df)
    assert out.iloc[0] == 0.0
