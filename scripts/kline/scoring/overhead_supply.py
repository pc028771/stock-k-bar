"""Overhead supply layer penalty score.

Course source: 【成本原理】層層套牢的結構判斷.

Counts swing-high peaks above current price in trailing 240 days as a
proxy for "layered trapped supply". Higher count = more resistance.

Required df columns: overhead_supply_layer (added by features pipeline).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series. Negative penalty for stacked overhead peaks.

      0 peaks    → 0
      1–3 peaks  → -5
      4+ peaks   → -15
    """
    layer = df["overhead_supply_layer"].fillna(0)
    s = pd.Series(0.0, index=df.index)
    s -= np.where(layer >= 4, 15, np.where(layer >= 1, 5, 0))
    return s
