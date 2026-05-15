"""SCORING_REGISTRY: includes all factors + stub returns zeros."""
from __future__ import annotations

from kline.scoring import SCORING_REGISTRY, shadow_position

from tests.conftest import make_bars


def test_registry_has_expected_factors():
    assert set(SCORING_REGISTRY.keys()) == {
        "attack_quality",
        "overhead_supply",
        "ma60_rolloff",
        "shadow_position",
    }


def test_shadow_position_stub_returns_zero():
    rows = [{"open": 100, "high": 101, "low": 99, "close": 100} for _ in range(3)]
    df = make_bars(rows)
    out = shadow_position.score(df)
    assert (out == 0.0).all()
    assert shadow_position.__doc__.startswith("STUB:")
