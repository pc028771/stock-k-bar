"""反撲型態 — context_only.

Course source: 第 22 篇《反撲型態》(207FAB90A1222E9DCD7CCE2A26AB19B7)
Cross-course definition: PATTERN_INVENTORY P23.
Engineering proxy constants: REBOUND_LOOKBACK_N.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import REBOUND_LOOKBACK_N


def detect(df: pd.DataFrame) -> pd.Series:
    """反撲型態 — 多方反撲 OR 空方反撲任一觸發.

    Conditions (PATTERN_INVENTORY P23):
      多方反撲 (跌勢中):
        1. D-1: 黑 K 創短期新低 (prev_low == rolling_min(low, N))
        2. D-0: 紅 K, open >= prev_open (開盤就站上 D-1 開盤)
      空方反撲 (漲勢中):
        1. D-1: 紅 K 創短期新高 (prev_high == rolling_max(high, N))
        2. D-0: 黑 K, open <= prev_open (開盤就跌破 D-1 開盤)

      區分於吞噬: 反撲關鍵在「開盤就直接反向」.
    """
    g = df.groupby("ticker")
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_high_v = g["high"].shift(1)
    prev_low_v = g["low"].shift(1)

    low_rollmin = (
        g["low"].rolling(REBOUND_LOOKBACK_N, min_periods=1)
        .min()
        .reset_index(level=0, drop=True)
    )
    high_rollmax = (
        g["high"].rolling(REBOUND_LOOKBACK_N, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
    )
    prev_low_is_min = prev_low_v <= g["low"].rolling(REBOUND_LOOKBACK_N, min_periods=1).min().reset_index(level=0, drop=True).shift(0)
    # simpler: prev_low == min over [D-1-N+1 .. D-1]
    prev_low_rollmin = (
        g["low"].rolling(REBOUND_LOOKBACK_N, min_periods=1)
        .min()
        .reset_index(level=0, drop=True)
        .groupby(df["ticker"]).shift(1)
    )
    prev_high_rollmax = (
        g["high"].rolling(REBOUND_LOOKBACK_N, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
        .groupby(df["ticker"]).shift(1)
    )

    prev_black = prev_close < prev_open
    prev_red = prev_close > prev_open
    today_red = df["close"] > df["open"]
    today_black = df["close"] < df["open"]

    prev_new_low = prev_low_v <= prev_low_rollmin
    prev_new_high = prev_high_v >= prev_high_rollmax

    bull_counter = prev_black & prev_new_low & today_red & (df["open"] >= prev_open)
    bear_counter = prev_red & prev_new_high & today_black & (df["open"] <= prev_open)

    # silence unused warnings
    _ = (low_rollmin, high_rollmax, prev_low_is_min)

    return (bull_counter | bear_counter).fillna(False)
