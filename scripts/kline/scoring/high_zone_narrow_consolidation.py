"""High-zone narrow consolidation bonus.

Course source: 型態學 14-攻擊型態三 推升攻擊.

> 「突破紅K後 N 天狹幅 + 低點不破突破點 = 推升攻擊的醞釀」

A stock in tight consolidation at high zone (after a recent breakout) is
in healthy attack醞釀, not weakness. This factor adds a bonus to such
candidates.

Detection:
  - Past N (say 6) bars have narrow range (within 5%)
  - Lowest low in window did NOT break below prior_high_60 (breakout point)
  - This indicates 主力 holding price up

Required df columns: high, low, close, prior_high_60.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..course_proxy_constants import (
    HIGH_ZONE_BONUS,
    HIGH_ZONE_CONSOLIDATION_DAYS as CONSOLIDATION_DAYS,
    HIGH_ZONE_NARROW_RANGE_MAX as NARROW_RANGE_MAX,
)

# Proxy: course says 「突破紅K 後 N 天狹幅 + 低點不破突破點 = 推升攻擊的醞釀」.
# Course gives no number for N or for "狹幅". We operationalize with a 6-bar
# window and a 5% range cap. See course_proxy_constants.I6.


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series. +8 for high-zone narrow consolidation."""
    g = df.groupby("ticker", group_keys=False)

    prior_max = pd.Series(
        g["high"].shift(1).rolling(CONSOLIDATION_DAYS, min_periods=CONSOLIDATION_DAYS).max()
        .reset_index(level=0, drop=True).values,
        index=df.index,
    )
    prior_min = pd.Series(
        g["low"].shift(1).rolling(CONSOLIDATION_DAYS, min_periods=CONSOLIDATION_DAYS).min()
        .reset_index(level=0, drop=True).values,
        index=df.index,
    )
    prior_mean = pd.Series(
        g["close"].shift(1).rolling(CONSOLIDATION_DAYS, min_periods=CONSOLIDATION_DAYS).mean()
        .reset_index(level=0, drop=True).values,
        index=df.index,
    )

    is_narrow = (prior_max - prior_min) / prior_mean.replace(0, float("nan")) <= NARROW_RANGE_MAX
    above_breakout = prior_min >= df["prior_high_60"]  # 低點不破突破點

    is_high_zone_narrow = is_narrow & above_breakout

    return pd.Series(np.where(is_high_zone_narrow, HIGH_ZONE_BONUS, 0.0), index=df.index)
