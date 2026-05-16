"""EXIT_REGISTRY: all conditions named correctly and registered."""
from __future__ import annotations

from kline.exit import EXIT_PRIORITY, EXIT_REGISTRY


def test_registry_has_all_intro_conditions():
    expected = {
        "gap_fill",
        "breakout_price_break",
        "breakout_low_break",
        "neckline_break",
        "trailing_stop",
        "trend_change",
        "prev_day_low_break",
        "gap_attack_filled",
        "sunrise_attack_end",
        "high_long_black",
        "supply_zone_reach",
        "ma60_neckline",
        "consolidation_breakdown",
        "reversal_k.dark_double_star",
        "reversal_k.bearish_engulfing",
        "reversal_k.enemy_at_gate",
        "reversal_k.evening_star",
        "reversal_k.two_crows",
        "reversal_k.gap_reversal",
    }
    assert expected.issubset(EXIT_REGISTRY.keys())


def test_priority_lists_all_registered_conditions():
    assert set(EXIT_PRIORITY) == set(EXIT_REGISTRY.keys())


def test_reversal_k_comes_first_in_priority():
    reversal_keys = [n for n in EXIT_PRIORITY if n.startswith("reversal_k.")]
    non_reversal_keys = [n for n in EXIT_PRIORITY if not n.startswith("reversal_k.")]
    # All reversal_k entries should appear before any non-reversal_k entry
    first_non_reversal_idx = EXIT_PRIORITY.index(non_reversal_keys[0])
    last_reversal_idx = max(EXIT_PRIORITY.index(k) for k in reversal_keys)
    assert last_reversal_idx < first_non_reversal_idx
