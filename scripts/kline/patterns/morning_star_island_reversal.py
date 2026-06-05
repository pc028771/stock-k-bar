"""晨星 + 島狀反轉 (低檔) — bull, exit (空單回補) — **非進場訊號** (課程明示).

Course source: 第 13 篇《晨星與島狀反轉》(29F3734E9FE458A7138B770EB29C29F8)
Cross-course definition: PATTERN_INVENTORY P14.
Engineering proxy constants: ISLAND_MAX_BARS.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import ISLAND_MAX_BARS
from ._common import bear_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """晨星 + 島狀反轉 (低檔) — 空方力竭 + 左缺口向下 + 右缺口向上.

    Conditions (PATTERN_INVENTORY P14):
      1. 空方力竭背景
      2. 過去 ≤ ISLAND_MAX_BARS 天曾出現向下跳空 (high < prev_low) → 左缺口
      3. 今日為向上跳空 (low > prev_high) → 右缺口

    Failure (留給上層 simulator): 右缺口隔天被回補 / 遇套牢區即失敗.
    """
    gap_down_any = (
        df["is_gap_down_today"].fillna(False).astype(int)
        .groupby(df["ticker"])
        .rolling(ISLAND_MAX_BARS, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
    )
    gap_down_recent = gap_down_any - df["is_gap_down_today"].fillna(False).astype(int) > 0

    gap_up_today = df["is_gap_up_today"].fillna(False)
    exhaust = bear_exhaustion_context(df)

    return (gap_down_recent & gap_up_today & exhaust).fillna(False)
