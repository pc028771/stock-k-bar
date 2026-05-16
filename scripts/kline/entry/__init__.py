"""Entry conditions for K-line course system.

Public API:
    ENTRY_REGISTRY: dict mapping condition name to detect() function.

External repos can also import individual conditions directly:
    from kline.entry.breakout import detect
"""
from __future__ import annotations

from . import breakout, sunrise, trend_reversal
from . import pattern_breakout_only as _pbo_module
from . import tweezer_top_breakout as _ttb_module

ENTRY_REGISTRY = {
    "breakout_attack": breakout.detect,
    "pattern_breakout_only": _pbo_module.detect,
    "tweezer_top_breakout": _ttb_module.detect,   # NEW
    "trend_reversal": trend_reversal.detect,
    "sunrise_attack": sunrise.detect,
}

# Convenience aliases so callers can do: from kline.entry import breakout_attack
breakout_attack = breakout.detect
pattern_breakout_only = _pbo_module.detect
tweezer_top_breakout = _ttb_module.detect
trend_reversal_entry = trend_reversal.detect
sunrise_attack = sunrise.detect

__all__ = [
    "ENTRY_REGISTRY",
    "breakout",
    "pattern_breakout_only",
    "tweezer_top_breakout",
    "sunrise",
    "trend_reversal",
    "breakout_attack",
    "trend_reversal_entry",
    "sunrise_attack",
]
