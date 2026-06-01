"""遭遇型態 — context_only.

Course source: 第 21 篇《遭遇型態》(4A2519730555027A6612FC9C77BE51FB)
Cross-course definition: PATTERN_INVENTORY P22.
Engineering proxy constants: BITE_CLOSE_EQUAL_TOLERANCE.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import BITE_CLOSE_EQUAL_TOLERANCE


def detect(df: pd.DataFrame) -> pd.Series:
    """遭遇型態 — 前日帶跳空力量 K + 今日反向收盤 ≈ 前日收盤 (缺口封閉).

    Conditions (PATTERN_INVENTORY P22):
      1. 前一日帶跳空 (前日 high < prev_prev_low OR 前日 low > prev_prev_high)
      2. 今日收盤 ≈ 前日收盤 (容差 0.1%)
      3. 顏色相反 (前紅今黑 OR 前黑今紅)
    """
    g = df.groupby("ticker")
    prev_close = g["close"].shift(1)
    prev_open = g["open"].shift(1)
    prev_high_v = g["high"].shift(1)
    prev_low_v = g["low"].shift(1)
    prev_prev_low = g["low"].shift(2)
    prev_prev_high = g["high"].shift(2)

    prev_gap_down = prev_high_v < prev_prev_low
    prev_gap_up = prev_low_v > prev_prev_high
    prev_was_gap = prev_gap_down | prev_gap_up

    close_eq = (df["close"] - prev_close).abs() / prev_close.replace(0, float("nan")) < BITE_CLOSE_EQUAL_TOLERANCE

    prev_red = prev_close > prev_open
    prev_black = prev_close < prev_open
    today_red = df["close"] > df["open"]
    today_black = df["close"] < df["open"]
    opposite = (prev_red & today_black) | (prev_black & today_red)

    return (prev_was_gap & close_eq & opposite).fillna(False)
