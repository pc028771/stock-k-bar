"""[EXTRAS] 空方單日反轉 — bear, exit (default OFF).

Course source: 第 15 篇《空方單日反轉》(5FCAA3846B5C453F95D59CBFE7ECEE20)
Cross-course definition: PATTERN_INVENTORY P16 + PATTERN_DEFINITIONS §4.

放在 extras/ 的理由：課程明示「**最微弱的轉折組合，容易誤判，需外部輔助**」。
依 CLAUDE.md「課程外條件隔離」精神，與其他形狀型態相比，本訊號必須等
其他確認 (跳空反轉 / 外側三黑 / 利多消息) 才有意義。
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """空方單日反轉 — 形狀層 detect (不含確認).

    Conditions (PATTERN_INVENTORY P16):
      1. D-1: 紅 K, high_{D-1} == prior_high_60 或創新高
      2. D-0: 黑 K, close < high_{D-1}, 但今日 high >= high_{D-1} (盤中觸高)
      3. 確認需另外加 (P09 跳空反轉 / P15 外側三黑 / 利多消息)
    """
    g = df.groupby("ticker")
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_high_v = g["high"].shift(1)
    prior_high_60_s = g["prior_high_60"].shift(1)

    prev_red = prev_close > prev_open
    prev_at_new_high = prev_high_v >= prior_high_60_s

    is_black = df["close"] < df["open"]
    touched_prev_high = df["high"] >= prev_high_v
    close_below_prev_high = df["close"] < prev_high_v

    return (prev_red & prev_at_new_high & is_black & touched_prev_high & close_below_prev_high).fillna(False)
