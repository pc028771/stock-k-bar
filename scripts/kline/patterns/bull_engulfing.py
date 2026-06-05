"""多頭吞噬 — bull, exit (空單回補) / context_only — **非進場訊號** (課程明示).

Course source: 第 02 篇《包覆線》(E79401532D60CC63B302926C2C33FB50)
Cross-course definition: PATTERN_DEFINITIONS.md §3 + PATTERN_INVENTORY P03.
"""
from __future__ import annotations

import pandas as pd

from ._common import bear_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """多頭吞噬 — 紅 K 實體包覆前日創新低黑 K + 空方力竭.

    Conditions (PATTERN_INVENTORY P03):
      1. 前一日黑 K (prev_close < prev_open)
      2. 前一日黑 K 創新低 (prev_low <= prior_low_60.shift(1))
      3. 今日紅 K 實體包覆 (open <= prev_close AND close >= prev_open)
      4. 空方力竭背景 (PATTERN_DEFINITIONS §3 — is_in_breakdown_pattern)

    WARNING: 課程明示「多頭吞噬本身不是買點」(PATTERN_DEFINITIONS §3 推導).
    本 detect 屬「空單回補」性質，僅供 trend_reversal 組合使用.
    """
    g = df.groupby("ticker")
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_low = g["low"].shift(1)
    prior_low_60_shift1 = g["prior_low_60"].shift(1)

    prev_is_black = prev_close < prev_open
    prev_new_low = prev_low <= prior_low_60_shift1

    is_red = df["close"] > df["open"]
    engulfs = (df["open"] <= prev_close) & (df["close"] >= prev_open)

    exhaust = bear_exhaustion_context(df)

    return (prev_is_black & prev_new_low & is_red & engulfs & exhaust).fillna(False)
