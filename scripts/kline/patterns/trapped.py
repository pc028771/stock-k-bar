"""內困型態 — context_only.

Course source: 第 23 篇《內困型態》(EBD01861796168390992499149DFE0EE)
Cross-course definition: PATTERN_INVENTORY P24.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """內困翻紅 OR 內困翻黑任一觸發.

    內困翻黑 (PATTERN_INVENTORY P24):
      1. D-2: 漲勢中創新高的紅 K (close_{D-2} > open_{D-2} AND close_{D-2} > prior_high_60.shift(2))
      2. D-1: 孕線 (high_{D-1} <= high_{D-2} AND low_{D-1} >= low_{D-2})
      3. D-0: 黑 K, close < D-2 之 low

    內困翻紅:
      1. D-2: 跌勢中創新低的黑 K (close_{D-2} < open_{D-2} AND low_{D-2} <= prior_low_60.shift(2))
      2. D-1: 孕線 (in D-2 range)
      3. D-0: 紅 K, close > D-2 之 high

    課程明示：與母子晨星 / 雙星很像但**沒有力竭背景**，故 context_only.
    """
    g = df.groupby("ticker")
    open_d2 = g["open"].shift(2)
    close_d2 = g["close"].shift(2)
    high_d2 = g["high"].shift(2)
    low_d2 = g["low"].shift(2)
    prior_high_60_d2 = g["prior_high_60"].shift(2)
    prior_low_60_d2 = g["prior_low_60"].shift(2)

    high_d1 = g["high"].shift(1)
    low_d1 = g["low"].shift(1)
    d1_harami_in_d2 = (high_d1 <= high_d2) & (low_d1 >= low_d2)

    # 內困翻黑
    d2_red_new_high = (close_d2 > open_d2) & (close_d2 > prior_high_60_d2)
    d0_black = df["close"] < df["open"]
    d0_breaks_d2_low = df["close"] < low_d2
    trap_black = d2_red_new_high & d1_harami_in_d2 & d0_black & d0_breaks_d2_low

    # 內困翻紅
    d2_black_new_low = (close_d2 < open_d2) & (low_d2 <= prior_low_60_d2)
    d0_red = df["close"] > df["open"]
    d0_breaks_d2_high = df["close"] > high_d2
    trap_red = d2_black_new_low & d1_harami_in_d2 & d0_red & d0_breaks_d2_high

    return (trap_black | trap_red).fillna(False)
