"""暗夜雙星 — bear, exit.

Course source: 第 07 篇《暗夜雙星》(426EAB98127A5370FC83CB5983BDA385)
Cross-course definition: PATTERN_INVENTORY P08.
Engineering proxy constants: SIDE_BY_SIDE_SIMILARITY_PCT.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..course_proxy_constants import SIDE_BY_SIDE_SIMILARITY_PCT
from ._common import bull_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """暗夜雙星 — 多方力竭 + D-2/D-1 併排相似 K + D-0 長黑跌破兩根低點.

    Conditions (PATTERN_INVENTORY P08):
      1. 多方力竭背景
      2. D-2, D-1: 兩根併排相似 K — |Δhigh|/high < 3% AND |Δlow|/low < 3%
      3. D-0: 黑 K, close < min(low_{D-2}, low_{D-1})
    """
    g = df.groupby("ticker")
    high_d2 = g["high"].shift(2)
    low_d2 = g["low"].shift(2)
    high_d1 = g["high"].shift(1)
    low_d1 = g["low"].shift(1)

    high_sim = (high_d1 - high_d2).abs() / high_d1.replace(0, np.nan) < SIDE_BY_SIDE_SIMILARITY_PCT
    low_sim = (low_d1 - low_d2).abs() / low_d1.replace(0, np.nan) < SIDE_BY_SIDE_SIMILARITY_PCT

    is_black = df["close"] < df["open"]
    min_low = pd.concat([low_d2, low_d1], axis=1).min(axis=1)
    breaks_pair = df["close"] < min_low

    exhaust = bull_exhaustion_context(df)

    return (high_sim & low_sim & is_black & breaks_pair & exhaust).fillna(False)
