"""supply_zone_reach STUB 已升級為 多空轉折組合 K 線 bearish patterns wrapper."""
from __future__ import annotations

from kline.exit import supply_zone_reach
from kline.features import add_features

from tests.conftest import make_bars


def _sample():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(5)]
    return add_features(make_bars(rows))


def test_supply_zone_reach_returns_bool_series():
    out = supply_zone_reach.mark(_sample())
    assert out.dtype == bool
    assert len(out) == 5
    # Flat 5-bar data should not trigger any bearish reversal pattern
    assert not out.any()


def test_supply_zone_reach_docstring_no_longer_stub():
    assert not supply_zone_reach.__doc__.startswith("STUB:")
