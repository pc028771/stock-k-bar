"""Reversal-K exit patterns.

One pattern per file. Currently dark_double_star is the only one with
intro-course structural definition; the other five are stubs awaiting
the 多空轉折組合K線 subcategory (26 articles).
"""
from __future__ import annotations

from . import (
    bearish_engulfing,
    dark_double_star,
    enemy_at_gate,
    evening_star,
    gap_reversal,
    two_crows,
)

REVERSAL_K_REGISTRY = {
    "dark_double_star": dark_double_star.mark,
    "bearish_engulfing": bearish_engulfing.mark,
    "enemy_at_gate": enemy_at_gate.mark,
    "evening_star": evening_star.mark,
    "two_crows": two_crows.mark,
    "gap_reversal": gap_reversal.mark,
}

__all__ = [
    "REVERSAL_K_REGISTRY",
    "bearish_engulfing", "dark_double_star", "enemy_at_gate",
    "evening_star", "gap_reversal", "two_crows",
]
