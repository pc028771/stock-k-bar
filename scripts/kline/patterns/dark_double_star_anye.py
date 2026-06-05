"""暗夜雙星 — bear, exit.

Course source: 第 07 篇《暗夜雙星》(426EAB98127A5370FC83CB5983BDA385)
Cross-course definition: PATTERN_INVENTORY P08.
Engineering proxy constants: SIDE_BY_SIDE_SIMILARITY_PCT.
"""
from __future__ import annotations

import pandas as pd

from ._common import bull_exhaustion_context, is_similar_bars


def detect(df: pd.DataFrame) -> pd.Series:
    """暗夜雙星 — 多方力竭 + D-2/D-1 併排相似 K + D-0 長黑跌破兩根低點.

    Conditions (PATTERN_INVENTORY P08, refactored to use _common helpers):
      1. 多方力竭背景 (bull_exhaustion_context)
      2. D-2, D-1: 兩根併排相似 K (is_similar_bars lookback 1+2)
      3. D-0: 黑 K, close < min(low_{D-2}, low_{D-1})
    """
    g = df.groupby("ticker")
    low_d2 = g["low"].shift(2)
    low_d1 = g["low"].shift(1)

    similar_pair = is_similar_bars(df, lookback1=1, lookback2=2)

    is_black = df["close"] < df["open"]
    min_low = pd.concat([low_d2, low_d1], axis=1).min(axis=1)
    breaks_pair = df["close"] < min_low

    exhaust = bull_exhaustion_context(df)

    return (similar_pair & is_black & breaks_pair & exhaust).fillna(False)
