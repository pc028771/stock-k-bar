"""Exit conditions for K-line course system.

Public API:
    EXIT_REGISTRY: dict mapping condition name → mark(df, entries) function.

Exit priority is determined per entry signal via:
    from kline.exit.groups import get_exit_priority
    priority = get_exit_priority(entry_name)
"""
from __future__ import annotations

from . import (
    breakout_low_break,
    breakout_price_break,
    consolidation_breakdown,
    gap_attack_filled,
    gap_fill,
    high_long_black,
    ma60_neckline,
    neckline_break,
    prev_day_low_break,
    sunrise_attack_end,
    supply_zone_reach,
    trailing_stop,
    trend_change,
)
from .groups import ENTRY_EXIT_GROUPS, EXIT_GROUPS, get_exit_priority
from .reversal_k import REVERSAL_K_REGISTRY

EXIT_REGISTRY = {
    "gap_fill":                  gap_fill.mark,
    "breakout_price_break":      breakout_price_break.mark,
    "breakout_low_break":        breakout_low_break.mark,
    "neckline_break":            neckline_break.mark,
    "trailing_stop":             trailing_stop.mark,
    "trend_change":              trend_change.mark,
    "prev_day_low_break":        prev_day_low_break.mark,
    "gap_attack_filled":         gap_attack_filled.mark,
    "sunrise_attack_end":        sunrise_attack_end.mark,
    "high_long_black":           high_long_black.mark,
    "supply_zone_reach":         supply_zone_reach.mark,
    "ma60_neckline":             ma60_neckline.mark,
    "consolidation_breakdown":   consolidation_breakdown.mark,
    **{f"reversal_k.{k}": v for k, v in REVERSAL_K_REGISTRY.items()},
}

__all__ = ["EXIT_REGISTRY", "EXIT_GROUPS", "ENTRY_EXIT_GROUPS", "get_exit_priority"]
