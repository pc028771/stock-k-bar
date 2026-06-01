"""遇壓跳空反轉 — bear, exit.

Course source: 第 07 篇附帶 + 第 08 篇延伸
Cross-course definition: PATTERN_INVENTORY P08b.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """遇壓跳空反轉 — 接近前壓 + 出現向下跳空.

    Conditions (PATTERN_INVENTORY P08b):
      1. 股價遇前波壓力 (overhead_supply_layer.shift(1) > 0)
      2. 今日向下跳空 (is_gap_down_today)
      3. 今日收盤未回補 (close < prev_low)
    """
    g = df.groupby("ticker")
    prev_overhead = g["overhead_supply_layer"].shift(1).fillna(0)
    has_overhead = prev_overhead > 0

    gap_down = df["is_gap_down_today"].fillna(False)
    no_fill = df["close"] < df["prev_low"]

    return (has_overhead & gap_down & no_fill).fillna(False)
