"""All reversal_k stubs return all-False."""
from __future__ import annotations

from kline.exit.reversal_k import (
    REVERSAL_K_REGISTRY,
    bearish_engulfing,
    enemy_at_gate,
    evening_star,
    gap_reversal,
    two_crows,
)

from tests.conftest import make_bars


def _sample():
    return make_bars([{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)])


def test_all_stubs_return_all_false():
    df = _sample()
    for mod in (bearish_engulfing, enemy_at_gate, evening_star, two_crows, gap_reversal):
        out = mod.mark(df)
        assert out.dtype == bool
        assert not out.any(), f"{mod.__name__} returned True somewhere"
        assert mod.__doc__.startswith("STUB:")


def test_registry_has_all_six_patterns():
    assert set(REVERSAL_K_REGISTRY.keys()) == {
        "dark_double_star",
        "bearish_engulfing",
        "enemy_at_gate",
        "evening_star",
        "two_crows",
        "gap_reversal",
    }
