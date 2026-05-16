"""Entry conditions for K-line course system.

Public API:
    ENTRY_REGISTRY: dict mapping condition name to detect() function.

External repos can also import individual conditions directly:
    from kline.entry.breakout import detect
"""
from __future__ import annotations

from . import breakout, sunrise, trend_reversal
from . import combined_pattern_or_tweezer as _cpot_module
from . import pattern_breakout_only as _pbo_module
from . import shoulder_gap_up_pullback as _sgup_module
from . import tweezer_top_breakout as _ttb_module
from . import tweezer_top_breakout_strict as _ttbs_module

ENTRY_REGISTRY = {
    "breakout_attack": breakout.detect,
    "pattern_breakout_only": _pbo_module.detect,
    "tweezer_top_breakout": _ttb_module.detect,
    "tweezer_top_breakout_strict": _ttbs_module.detect,
    "shoulder_gap_up_pullback": _sgup_module.detect,
    "trend_reversal": trend_reversal.detect,
    "sunrise_attack": sunrise.detect,
    "combined_pattern_or_tweezer": _cpot_module.detect,
}

# Convenience aliases so callers can do: from kline.entry import breakout_attack
breakout_attack = breakout.detect
pattern_breakout_only = _pbo_module.detect
tweezer_top_breakout = _ttb_module.detect
tweezer_top_breakout_strict = _ttbs_module.detect
shoulder_gap_up_pullback = _sgup_module.detect
trend_reversal_entry = trend_reversal.detect
sunrise_attack = sunrise.detect
combined_pattern_or_tweezer = _cpot_module.detect

__all__ = [
    "ENTRY_REGISTRY",
    "breakout",
    "combined_pattern_or_tweezer",
    "pattern_breakout_only",
    "tweezer_top_breakout",
    "tweezer_top_breakout_strict",
    "shoulder_gap_up_pullback",
    "sunrise",
    "trend_reversal",
    "breakout_attack",
    "trend_reversal_entry",
    "sunrise_attack",
]
