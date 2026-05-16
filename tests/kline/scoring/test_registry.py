"""SCORING_REGISTRY: includes all factors + stub returns zeros."""
from __future__ import annotations

from kline.scoring import SCORING_REGISTRY, shadow_position

from tests.conftest import make_bars


def test_registry_has_expected_factors():
    assert set(SCORING_REGISTRY.keys()) == {
        "overhead_supply",
        "ma60_rolloff",
        "shadow_position",
        "pattern_breakout",
        "attack_intensity",
        "high_zone_narrow_consolidation",
        "trend_continuation",
    }


def test_shadow_position_returns_zero_for_neutral_bars():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    df["prior_high_60"] = [100.0, 100.0, 100.0]
    df["upper_shadow_ratio"] = [0.0, 0.0, 0.0]
    df["overhead_supply_layer"] = [0.0, 0.0, 0.0]
    df["is_red"] = [False, False, False]
    out = shadow_position.score(df)
    assert (out == 0.0).all()
    # No longer a STUB
    assert not shadow_position.__doc__.lstrip().startswith("STUB:")
