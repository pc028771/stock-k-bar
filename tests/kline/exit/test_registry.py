"""EXIT_REGISTRY: all conditions named correctly and registered."""
from __future__ import annotations

from kline.exit import EXIT_GROUPS, EXIT_REGISTRY


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


def test_all_group_exits_are_in_registry():
    """Every exit name referenced in EXIT_GROUPS must exist in EXIT_REGISTRY."""
    for group_name, exits in EXIT_GROUPS.items():
        for exit_name in exits:
            assert exit_name in EXIT_REGISTRY, (
                f"Group '{group_name}' references '{exit_name}' "
                f"which is not in EXIT_REGISTRY"
            )


def test_strong_attack_group_has_expected_keys():
    group = EXIT_GROUPS["strong_attack"]
    assert "reversal_k.dark_double_star" in group
    assert "high_long_black" in group
    assert "gap_fill" in group
    assert "breakout_low_break" in group


def test_trend_change_group_separated_from_strong_attack():
    strong = set(EXIT_GROUPS["strong_attack"])
    trend = set(EXIT_GROUPS["trend_change"])
    # trend_change and ma60_neckline should only be in trend_change group
    assert "trend_change" in trend
    assert "trend_change" not in strong
    assert "ma60_neckline" in trend
    assert "ma60_neckline" not in strong


def test_slow_push_group_has_trailing_stop():
    assert EXIT_GROUPS["slow_push"] == ["trailing_stop"]


def test_short_term_group_has_prev_day_low_break():
    assert EXIT_GROUPS["short_term"] == ["prev_day_low_break"]
