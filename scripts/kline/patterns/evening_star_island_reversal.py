"""夜星 + 島狀反轉 (高檔) — bear, exit.

Course source: 第 12 篇《夜星與島狀反轉》(6C03240289991A8B7F5D99C5DC2409D5)
Cross-course definition: PATTERN_INVENTORY P13.
Engineering proxy constants: ISLAND_MAX_BARS.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import ISLAND_MAX_BARS
from ._common import bull_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """夜星 + 島狀反轉 (高檔) — 多方力竭 + 左缺口向上 + 右缺口向下 (≤10 天).

    Conditions (PATTERN_INVENTORY P13):
      1. 多方力竭背景
      2. 過去 ≤ ISLAND_MAX_BARS 天內曾出現「向上跳空」(low > prev_high) → 左缺口
      3. 今日是「向下跳空」(high < prev_low) → 右缺口
      4. 「重意不重形」 — 只看右側向下跳空即觸發 (PATTERN_INVENTORY 第 5 點)
    """
    g = df.groupby("ticker")
    gap_up_any = (
        df["is_gap_up_today"].fillna(False).astype(int)
        .groupby(df["ticker"])
        .rolling(ISLAND_MAX_BARS, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
    )
    # 排除今天自己 — left gap 必須在「過去」幾天
    gap_up_recent = gap_up_any - df["is_gap_up_today"].fillna(False).astype(int) > 0

    gap_down_today = df["is_gap_down_today"].fillna(False)
    exhaust = bull_exhaustion_context(df)

    return (gap_up_recent & gap_down_today & exhaust).fillna(False)
