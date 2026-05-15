"""Entry conditions for K-line course system.

Public API:
    ENTRY_REGISTRY: dict mapping condition name to detect() function.

External repos can also import individual conditions directly:
    from kline.entry.breakout import detect
"""
from __future__ import annotations

from . import breakout, sunrise, trend_reversal

ENTRY_REGISTRY = {
    "breakout_attack": breakout.detect,
    "trend_reversal": trend_reversal.detect,
    "sunrise_attack": sunrise.detect,
}

__all__ = ["ENTRY_REGISTRY", "breakout", "sunrise", "trend_reversal"]
