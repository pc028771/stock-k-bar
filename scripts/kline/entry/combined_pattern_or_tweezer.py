"""Combined entry: pattern_breakout_only OR tweezer_top_breakout.

This is a UNION of two course-faithful entry signals:
  - pattern_breakout_only: 5-condition strict 起點 entry (型態學 03+05+08+14)
  - tweezer_top_breakout: 鑷頂突破 + clean overhead (型態學 18)

Rationale: both detect 起點-style entries but from different K-line geometries.
Combining them widens the candidate pool while keeping each leg course-faithful.

Note: a trade signal here fires if EITHER pattern or tweezer fires on a given bar.
Per-trade dedup is handled by the simulator (one trade per signal).

Required df columns: all columns required by pattern_breakout_only and
                      tweezer_top_breakout (already in add_features output).
"""
from __future__ import annotations

import pandas as pd

from .pattern_breakout_only import detect as pattern_detect
from .tweezer_top_breakout import detect as tweezer_detect


def detect(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = either pattern OR tweezer triggered."""
    return (pattern_detect(df) | tweezer_detect(df)).fillna(False)
