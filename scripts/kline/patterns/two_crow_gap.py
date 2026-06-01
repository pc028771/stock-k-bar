"""雙鴉躍空 — bear, exit.

Course source: 第 09 篇《雙鴉躍空》(13041D9897DBD12852724CAD0D994486)
Cross-course definition: PATTERN_INVENTORY P10.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """雙鴉躍空 — 遇壓 + 紅 K + 雙黑鴉 + D-0 開低跳空.

    Conditions (PATTERN_INVENTORY P10):
      1. 遇壓背景 (overhead_supply_layer > 0 on D-3)
      2. D-3: 紅 K (open > prev_close — 開高)
      3. D-2, D-1: 兩根黑 K (含短黑、十字線)
      4. D-0: open < prev_low (開盤跳空向下)
    """
    g = df.groupby("ticker")
    overhead_d3 = g["overhead_supply_layer"].shift(3).fillna(0)
    overhead_ok = overhead_d3 > 0

    open_d3 = g["open"].shift(3)
    close_d3 = g["close"].shift(3)
    close_d4 = g["close"].shift(4)
    d3_red_open_high = (close_d3 > open_d3) & (open_d3 > close_d4)

    open_d2 = g["open"].shift(2)
    close_d2 = g["close"].shift(2)
    open_d1 = g["open"].shift(1)
    close_d1 = g["close"].shift(1)
    d2_black = close_d2 < open_d2
    d1_black = close_d1 < open_d1

    prev_low_v = g["low"].shift(1)
    d0_gap_down_open = df["open"] < prev_low_v

    return (overhead_ok & d3_red_open_high & d2_black & d1_black & d0_gap_down_open).fillna(False)
