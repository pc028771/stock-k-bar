"""母子晨星 / 母子雙星 — bull, exit (空單回補).

Course source: 第 03 篇《孕線：母子晨星》(978854A6B0757492FB6A99F8E92A41EC)
              + 第 05 篇《母子雙星》(8303539A2CA4AC0E8FEB24E68BABF933)
Cross-course definition: PATTERN_DEFINITIONS.md §3 + PATTERN_INVENTORY P04, P06.

涵蓋兩變體：
  - 母子晨星 (2 K): D-1 長黑破底 + D-0 紅 K 孕線收盤站上中值
  - 母子雙星 (3 K): D-2 長黑破底 + D-1 紅 K 孕線收未過中值 + D-0 收盤站上中值
"""
from __future__ import annotations

import pandas as pd

from ._common import bear_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """母子晨星 OR 母子雙星 — 兩變體任一觸發即 True.

    Conditions (PATTERN_INVENTORY P04):
      1. 空方力竭背景
      2. 前一日為破底長黑 (prev_low <= prior_low_60.shift(1) AND prev_close < prev_open)
      3. 今日為紅 K 孕線 (is_red AND is_harami)
      4. 今日收盤站上前日中值 (close >= (prev_open + prev_close) / 2)

    P06 變體 (3 K) — 第 03 日收盤站上 D-2 中值:
      D-2: 長黑破底; D-1: 紅 K 孕線但 close < D-2 中值; D-0: close >= D-2 中值.
    """
    g = df.groupby("ticker")
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_low = g["low"].shift(1)
    prior_low_60_shift1 = g["prior_low_60"].shift(1)

    prev_is_black = prev_close < prev_open
    prev_breakdown = prev_low <= prior_low_60_shift1

    is_red = df["close"] > df["open"]
    today_harami = df["is_harami"].fillna(False)
    prev_mid = (prev_open + prev_close) / 2
    today_close_above_mid = df["close"] >= prev_mid

    exhaust = bear_exhaustion_context(df)

    p04 = (
        prev_is_black & prev_breakdown & is_red & today_harami
        & today_close_above_mid & exhaust
    )

    # P06: 三根變體 — D-2 長黑破底, D-1 紅孕但未過中值, D-0 站上 D-2 中值
    open_d2 = g["open"].shift(2)
    close_d2 = g["close"].shift(2)
    low_d2 = g["low"].shift(2)
    prior_low_60_shift2 = g["prior_low_60"].shift(2)
    d1_close = prev_close
    d1_open = prev_open
    d1_high = g["high"].shift(1)
    d1_low = prev_low
    d2_high = g["high"].shift(2)

    d2_is_long_black = (close_d2 < open_d2) & (low_d2 <= prior_low_60_shift2)
    d1_is_red = d1_close > d1_open
    d1_harami_of_d2 = (d1_high <= d2_high) & (d1_low >= low_d2)
    d2_mid = (open_d2 + close_d2) / 2
    d1_close_below_mid = d1_close < d2_mid
    d0_close_above_mid = df["close"] >= d2_mid

    p06 = (
        d2_is_long_black & d1_is_red & d1_harami_of_d2
        & d1_close_below_mid & d0_close_above_mid & exhaust
    )

    return (p04 | p06).fillna(False)
