"""上缺口被回補 (多方力量消失) — context_only.

Course source: 第 26 篇《上下缺回補型態組合的輔助》(5CB9CD820B2BEF0AC861FFEDB89CD6B0)
Cross-course definition: PATTERN_INVENTORY P27.
Engineering proxy constants: GAP_FILL_WINDOW_DAYS.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import GAP_FILL_WINDOW_DAYS
from ._common import fast_shift


def detect(df: pd.DataFrame) -> pd.Series:
    """向上跳空缺口被回補 — N 日前出現向上跳空 + 今日 close < 該日 prev_high.

    Conditions (PATTERN_INVENTORY P27):
      1. 過去 GAP_FILL_WINDOW_DAYS 日內某日為 gap up (low_{D-k} > high_{D-k-1})
      2. 今日 close <= 該日的 prev_high (gap_bottom)
      3. 今日為實際回補日 (前一日 close > gap_bottom, 今日 close <= gap_bottom)
    """
    # Pre-shift once per (col, lag) to avoid 2× groupby ops per loop iteration.
    # Single-ticker fast-path also avoids groupby overhead entirely.
    low_today = df["low"]
    low_yesterday = fast_shift(df, "low", 1)
    # We need low.shift(k) for k=1..N and high.shift(k) for k=2..N+1.
    low_shifts: dict[int, pd.Series] = {1: low_yesterday}
    high_shifts: dict[int, pd.Series] = {}
    for k in range(1, GAP_FILL_WINDOW_DAYS + 2):
        if k not in low_shifts:
            low_shifts[k] = fast_shift(df, "low", k)
        if k not in high_shifts:
            high_shifts[k] = fast_shift(df, "high", k)

    result = pd.Series(False, index=df.index)
    for lag in range(1, GAP_FILL_WINDOW_DAYS + 1):
        past_low = low_shifts[lag]
        past_prev_high = high_shifts[lag + 1]
        was_gap_up = past_low > past_prev_high
        gap_bottom = past_prev_high
        today_filled = low_today <= gap_bottom  # intraday touch counts
        yesterday_above = low_yesterday > gap_bottom
        result = result | (was_gap_up & today_filled & yesterday_above).fillna(False)

    return result.fillna(False)
