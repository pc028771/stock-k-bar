"""突破雙星 (低檔築底突破) — bull, exit (空單回補) / 弱勢進場觀察.

Course source: 第 10 篇《突破雙星》(EDFE0FB85503F88DFB6696C9EACA00D4)
Cross-course definition: PATTERN_INVENTORY P11.
Engineering proxy constants: SIDE_BY_SIDE_SIMILARITY_PCT.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..course_proxy_constants import SIDE_BY_SIDE_SIMILARITY_PCT
from ._common import bear_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """突破雙星 — 低檔整理 + D-3/D-2 併排 + D-1 紅 K 突破 + D-0 跳空向上確認.

    Conditions (PATTERN_INVENTORY P11):
      1. 空方力竭/低檔整理背景
      2. D-3, D-2: 兩根併排 K (similar high/low)
      3. D-1: 紅 K, close > max(high_{D-3}, high_{D-2})
      4. D-0: open > prev_high (跳空向上確認)
    """
    g = df.groupby("ticker")
    high_d3 = g["high"].shift(3)
    low_d3 = g["low"].shift(3)
    high_d2 = g["high"].shift(2)
    low_d2 = g["low"].shift(2)

    high_sim = (high_d2 - high_d3).abs() / high_d2.replace(0, np.nan) < SIDE_BY_SIDE_SIMILARITY_PCT
    low_sim = (low_d2 - low_d3).abs() / low_d2.replace(0, np.nan) < SIDE_BY_SIDE_SIMILARITY_PCT

    open_d1 = g["open"].shift(1)
    close_d1 = g["close"].shift(1)
    high_d1 = g["high"].shift(1)
    d1_red = close_d1 > open_d1
    d1_breaks_pair = close_d1 > pd.concat([high_d3, high_d2], axis=1).max(axis=1)

    d0_gap_up = df["open"] > high_d1

    exhaust = bear_exhaustion_context(df)

    return (high_sim & low_sim & d1_red & d1_breaks_pair & d0_gap_up & exhaust).fillna(False)
