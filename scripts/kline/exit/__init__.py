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
    gap_attack_filled,
    high_long_black,
    just_high_upper_shadow_low_break,
    ma60_neckline,
    prev_day_low_break,
    sunrise_attack_end,
    supply_zone_reach,
    trailing_stop,
    trend_change,
)
from .groups import ENTRY_EXIT_GROUPS, EXIT_GROUPS, get_exit_priority
from .reversal_k import REVERSAL_K_REGISTRY

EXIT_REGISTRY = {
    "breakout_price_break":      breakout_price_break.mark,
    "breakout_low_break":        breakout_low_break.mark,
    "trailing_stop":             trailing_stop.mark,
    "trailing_stop_slow_push":   trailing_stop.mark_slow_push,
    "trailing_stop_weak_bull":   trailing_stop.mark_weak_bull,
    "trend_change":              trend_change.mark,
    "prev_day_low_break":        prev_day_low_break.mark,
    "gap_attack_filled":         gap_attack_filled.mark,
    "sunrise_attack_end":        sunrise_attack_end.mark,
    "high_long_black":           high_long_black.mark,
    "supply_zone_reach":         supply_zone_reach.mark,
    "ma60_neckline":             ma60_neckline.mark,
    "just_high_upper_shadow_low_break": just_high_upper_shadow_low_break.mark,
    **{f"reversal_k.{k}": v for k, v in REVERSAL_K_REGISTRY.items()},
}

__all__ = ["EXIT_REGISTRY", "EXIT_GROUPS", "ENTRY_EXIT_GROUPS", "get_exit_priority"]
