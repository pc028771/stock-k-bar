"""Overhead supply layer penalty score.

Course source: 【成本原理】層層套牢的結構判斷.

Counts swing-high peaks above current price in trailing 240 days as a
proxy for "layered trapped supply". Higher count = more resistance.

Required df columns: overhead_supply_layer (added by features pipeline).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..course_proxy_constants import (
    OVERHEAD_HEAVY_MIN_PEAKS,
    OVERHEAD_HEAVY_PENALTY,
    OVERHEAD_LIGHT_PENALTY,
)


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series. Negative penalty for stacked overhead peaks.

    Proxy: course (層層套牢) says layered supply = real resistance but does
    NOT tier resistance by peak count. The 1–3 / 4+ split and the -5 / -15
    magnitudes are our operationalization. See course_proxy_constants.I5.

      0 peaks    → 0
      1–3 peaks  → -5  (proxy, course-not-stated)
      4+ peaks   → -15 (proxy, course-not-stated)
    """
    layer = df["overhead_supply_layer"].fillna(0)
    s = pd.Series(0.0, index=df.index)
    # Constants are negative; subtracting their absolute value preserves
    # the original "-5 / -15" output behavior.
    s += np.where(
        layer >= OVERHEAD_HEAVY_MIN_PEAKS,
        OVERHEAD_HEAVY_PENALTY,
        np.where(layer >= 1, OVERHEAD_LIGHT_PENALTY, 0),
    )
    return s
