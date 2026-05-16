"""Test exit groups + entry mapping."""
from __future__ import annotations

import pytest
from kline.exit.groups import ENTRY_EXIT_GROUPS, EXIT_GROUPS, get_exit_priority


def test_strong_attack_includes_reversal_k_patterns():
    group = EXIT_GROUPS["strong_attack"]
    assert "reversal_k.dark_double_star" in group
    assert "high_long_black" in group
    assert "sunrise_attack_end" in group


def test_strong_attack_does_not_include_trend_change():
    group = EXIT_GROUPS["strong_attack"]
    assert "trend_change" not in group
    assert "ma60_neckline" not in group


def test_trend_change_separated():
    group = EXIT_GROUPS["trend_change"]
    assert "trend_change" in group
    assert "ma60_neckline" in group
    assert "reversal_k.dark_double_star" not in group


def test_short_term_only_prev_day_low_break():
    group = EXIT_GROUPS["short_term"]
    assert group == ["prev_day_low_break"]


def test_tweezer_uses_strong_attack_group():
    priority = get_exit_priority("tweezer_top_breakout")
    # Should include reversal_k + strong_attack-related, NOT trend_change
    assert "reversal_k.dark_double_star" in priority
    assert "sunrise_attack_end" in priority
    assert "high_long_black" in priority
    # Should NOT include
    assert "trend_change" not in priority
    assert "ma60_neckline" not in priority
    assert "prev_day_low_break" not in priority
    assert "trailing_stop" not in priority


def test_tweezer_includes_supply_zone_and_consolidation():
    priority = get_exit_priority("tweezer_top_breakout")
    assert "supply_zone_reach" in priority
    assert "consolidation_breakdown" in priority


def test_trend_reversal_uses_trend_change_group():
    priority = get_exit_priority("trend_reversal")
    assert "trend_change" in priority
    assert "ma60_neckline" in priority
    assert "supply_zone_reach" in priority
    # reversal_k not in trend_change group
    assert "reversal_k.dark_double_star" not in priority


def test_get_exit_priority_deduplicates():
    """get_exit_priority must not repeat entries even if groups overlap."""
    priority = get_exit_priority("breakout_attack")
    assert len(priority) == len(set(priority))


def test_all_entry_names_have_mapping():
    """Every ENTRY_EXIT_GROUPS key should resolve without error."""
    for entry_name in ENTRY_EXIT_GROUPS:
        result = get_exit_priority(entry_name)
        assert isinstance(result, list)
        assert len(result) > 0


def test_unknown_entry_raises():
    with pytest.raises(ValueError, match="No exit groups defined"):
        get_exit_priority("nonexistent_entry")
