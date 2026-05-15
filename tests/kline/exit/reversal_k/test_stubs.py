"""Registry completeness test for reversal_k patterns."""
from __future__ import annotations

from kline.exit.reversal_k import REVERSAL_K_REGISTRY


def test_registry_has_all_six_patterns():
    assert set(REVERSAL_K_REGISTRY.keys()) == {
        "dark_double_star",
        "bearish_engulfing",
        "enemy_at_gate",
        "evening_star",
        "two_crows",
        "gap_reversal",
    }
