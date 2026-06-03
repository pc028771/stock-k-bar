"""下缺口被回補 (空方力量消失) — context_only.

Course source: 第 26 篇《上下缺回補型態組合的輔助》(5CB9CD820B2BEF0AC861FFEDB89CD6B0)
Cross-course definition: PATTERN_INVENTORY P27.
Engineering proxy constants: GAP_FILL_WINDOW_DAYS.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import GAP_FILL_WINDOW_DAYS


def detect(df: pd.DataFrame) -> pd.Series:
    """向下跳空缺口被回補 — N 日前出現向下跳空 + 今日 close > 該日 prev_low.

    Conditions (PATTERN_INVENTORY P27):
      1. 過去 GAP_FILL_WINDOW_DAYS 日內某日為 gap down (high_{D-k} < low_{D-k-1})
      2. 今日 close >= 該日的 prev_low (gap_top)
      3. 今日為實際回補日 (前一日 close < gap_top, 今日 close >= gap_top)
    """
    # Course「隔日就回補」allows intraday touch (high >= gap_top), not strict
    # close >= gap_top. Case #14 6278 台表科 2018-09-19: high 34.65 exactly
    # equals 09-18 gap_top 34.65, but close 33.95 < gap_top — intraday touch
    # confirms「缺口回補」per chartists' definition.
    g = df.groupby("ticker")
    high_today = df["high"]
    high_yesterday = g["high"].shift(1)

    result = pd.Series(False, index=df.index)
    for lag in range(1, GAP_FILL_WINDOW_DAYS + 1):
        past_high = g["high"].shift(lag)
        past_prev_low = g["low"].shift(lag + 1)
        was_gap_down = past_high < past_prev_low
        gap_top = past_prev_low
        today_filled = high_today >= gap_top  # intraday touch counts
        yesterday_below = high_yesterday < gap_top  # yesterday hadn't yet touched
        result = result | (was_gap_down & today_filled & yesterday_below).fillna(False)

    return result.fillna(False)
