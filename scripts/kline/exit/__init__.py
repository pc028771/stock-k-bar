"""Exit conditions for K-line course system.

Public API:
    EXIT_REGISTRY: dict mapping condition name to mark(df, entries) function.
    EXIT_PRIORITY: list of condition names, highest priority first.

External repos can also import individual conditions directly:
    from kline.exit.gap_fill import mark
"""
from __future__ import annotations

from . import (
    breakout_low_break,
    gap_fill,
    ma60_neckline,
    neckline_break,
    prev_day_low_break,
    supply_zone_reach,
    trailing_stop,
    trend_change,
)
from .reversal_k import REVERSAL_K_REGISTRY

EXIT_REGISTRY = {
    "gap_fill":            gap_fill.mark,
    "breakout_low_break":  breakout_low_break.mark,
    "neckline_break":      neckline_break.mark,
    "trailing_stop":       trailing_stop.mark,
    "trend_change":        trend_change.mark,
    "prev_day_low_break":  prev_day_low_break.mark,
    "supply_zone_reach":   supply_zone_reach.mark,
    "ma60_neckline":       ma60_neckline.mark,
    **{f"reversal_k.{k}": v for k, v in REVERSAL_K_REGISTRY.items()},
}

# Spec §5.1 — highest priority first
EXIT_PRIORITY = [
    "reversal_k.dark_double_star",
    "reversal_k.bearish_engulfing",
    "reversal_k.enemy_at_gate",
    "reversal_k.evening_star",
    "reversal_k.two_crows",
    "reversal_k.gap_reversal",
    "gap_fill",
    "breakout_low_break",
    "neckline_break",
    "prev_day_low_break",
    "trailing_stop",
    "trend_change",
    "supply_zone_reach",
    "ma60_neckline",
]

__all__ = ["EXIT_REGISTRY", "EXIT_PRIORITY"]
