"""上缺口被回補 (多方力量消失) — context_only.

Course source: 第 26 篇《上下缺回補型態組合的輔助》(5CB9CD820B2BEF0AC861FFEDB89CD6B0)
Cross-course definition: PATTERN_INVENTORY P27.
Engineering proxy constants: GAP_FILL_WINDOW_DAYS.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import GAP_FILL_WINDOW_DAYS


def detect(df: pd.DataFrame) -> pd.Series:
    """向上跳空缺口被回補 — N 日前出現向上跳空 + 今日 close < 該日 prev_high.

    Conditions (PATTERN_INVENTORY P27):
      1. 過去 GAP_FILL_WINDOW_DAYS 日內某日為 gap up (low_{D-k} > high_{D-k-1})
      2. 今日 close <= 該日的 prev_high (gap_bottom)
      3. 今日為實際回補日 (前一日 close > gap_bottom, 今日 close <= gap_bottom)
    """
    g = df.groupby("ticker")
    close_today = df["close"]
    close_yesterday = g["close"].shift(1)

    result = pd.Series(False, index=df.index)
    for lag in range(1, GAP_FILL_WINDOW_DAYS + 1):
        past_low = g["low"].shift(lag)
        past_prev_high = g["high"].shift(lag + 1)
        was_gap_up = past_low > past_prev_high
        # gap_bottom = past_prev_high (上邊界 of gap, 也是回補要破下的價位)
        gap_bottom = past_prev_high
        # 今日剛被回補 (前日仍上方, 今日跌破)
        today_filled = close_today <= gap_bottom
        yesterday_above = close_yesterday > gap_bottom
        result = result | (was_gap_up & today_filled & yesterday_above).fillna(False)

    return result.fillna(False)
