"""overhead_supply.score: penalty for stacked overhead resistance peaks."""
from __future__ import annotations

from kline.scoring.overhead_supply import score

from tests.conftest import make_bars


def test_clean_overhead_returns_zero_penalty():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["overhead_supply_layer"] = [0.0]
    out = score(df)
    assert out.iloc[0] == 0.0


def test_heavy_overhead_returns_negative_penalty():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(1)]
    df = make_bars(rows)
    df["overhead_supply_layer"] = [5.0]
    out = score(df)
    assert out.iloc[0] < 0
