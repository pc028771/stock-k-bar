"""Verify exit stubs return all-False."""
from __future__ import annotations

from kline.exit import supply_zone_reach

from tests.conftest import make_bars


def _sample():
    return make_bars([{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)])


def test_supply_zone_reach_stub():
    out = supply_zone_reach.mark(_sample())
    assert out.dtype == bool
    assert not out.any()
    assert len(out) == 3


def test_stubs_have_stub_marker_in_docstring():
    assert supply_zone_reach.__doc__.startswith("STUB:")
