"""high_zone_narrow_consolidation scoring tests."""
from __future__ import annotations

from kline.scoring.high_zone_narrow_consolidation import score

from tests.conftest import make_bars


def test_fires_after_narrow_consolidation_at_high():
    """6 bars narrow range, low > prior_high_60 → bonus."""
    bar = {"open": 100, "high": 102, "low": 100, "close": 101, "volume": 1000.0}
    rows = [bar] * 6
    rows.append({"open": 101, "high": 105, "low": 100, "close": 103, "volume": 1000.0})
    df = make_bars(rows)
    df["prior_high_60"] = [99.0] * 7  # breakout point below the consolidation low
    out = score(df)
    assert out.iloc[6] > 0


def test_does_not_fire_if_low_breaks_prior_high():
    """Consolidation low below breakout point → not high-zone."""
    rows = [{"open": 95, "high": 97, "low": 93, "close": 95, "volume": 1000.0} for _ in range(6)]
    rows.append({"open": 95, "high": 100, "low": 94, "close": 99, "volume": 1000.0})
    df = make_bars(rows)
    df["prior_high_60"] = [99.0] * 7
    out = score(df)
    assert out.iloc[6] == 0


def test_does_not_fire_with_wide_range():
    """Wide range (>5%) → not narrow → no bonus."""
    rows = [{"open": 100, "high": 110, "low": 95, "close": 100, "volume": 1000.0} for _ in range(6)]
    rows.append({"open": 100, "high": 110, "low": 95, "close": 100, "volume": 1000.0})
    df = make_bars(rows)
    df["prior_high_60"] = [99.0] * 7
    out = score(df)
    assert out.iloc[6] == 0


def test_returns_zero_without_enough_history():
    """Fewer than CONSOLIDATION_DAYS bars → NaN → fills to 0."""
    bar = {"open": 100, "high": 102, "low": 100, "close": 101, "volume": 1000.0}
    rows = [bar] * 4
    df = make_bars(rows)
    df["prior_high_60"] = [99.0] * 4
    out = score(df)
    assert (out == 0.0).all()
