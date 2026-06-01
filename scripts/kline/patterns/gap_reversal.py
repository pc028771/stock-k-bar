"""跳空反轉 — bear, exit.

Course source: 第 08 篇《跳空反轉》(92E64EAB9982ADE91CB903046E5FA04F)
Cross-course definition: PATTERN_INVENTORY P09.
"""
from __future__ import annotations

import pandas as pd

from ._common import bull_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """跳空反轉 — 多方力竭/遇壓 + 今日向下跳空 + 無力回補.

    Conditions (PATTERN_INVENTORY P09):
      1. 多方力竭背景 (D-2 / 近期創新高)
      2. 今日 open < prev_low (向下跳空)
      3. 今日 close < prev_low (收盤無力回補)
    """
    g = df.groupby("ticker")
    prev_low_v = g["low"].shift(1)
    gap_down_open = df["open"] < prev_low_v
    no_fill_close = df["close"] < prev_low_v

    exhaust = bull_exhaustion_context(df)

    return (gap_down_open & no_fill_close & exhaust).fillna(False)
