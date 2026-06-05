"""[EXTRAS] 多方單日反轉 — bull, exit (空單回補) — **絕對不是買進訊號** (default OFF).

Course source: 第 16 篇《多方單日反轉》(9D8B76607439F24FB8AD2026044D988B)
Cross-course definition: PATTERN_INVENTORY P17 + PATTERN_DEFINITIONS §4.

放在 extras/ 的理由：同 bear_single_day_reversal — 課程明示需外部輔助.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """多方單日反轉 — 形狀層 detect.

    Conditions (PATTERN_INVENTORY P17):
      1. D-1: 長黑 K, low_{D-1} == prior_low_60 或創新低
      2. D-0: 紅 K, close > low_{D-1}, 但今日 low < low_{D-1} (盤中破低)
      3. 課程明示「只能等不再破底，不可當買點」
    """
    g = df.groupby("ticker")
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_low_v = g["low"].shift(1)
    prior_low_60_s = g["prior_low_60"].shift(1)

    prev_black = prev_close < prev_open
    prev_at_new_low = prev_low_v <= prior_low_60_s

    is_red = df["close"] > df["open"]
    broke_prev_low = df["low"] < prev_low_v
    close_above_prev_low = df["close"] > prev_low_v

    return (prev_black & prev_at_new_low & is_red & broke_prev_low & close_above_prev_low).fillna(False)
