"""外側三黑 — bear, exit.

Course source: 第 14 篇《黑三兵與外側三黑》(71B4F99819BB5207A78994BEC40FC79D)
Cross-course definition: PATTERN_INVENTORY P15 + PATTERN_DEFINITIONS §1 結論 2.
Engineering proxy constants: HIGH_LONG_BLACK_BODY_PCT_MIN (唯一保留 body 門檻場合).
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import HIGH_LONG_BLACK_BODY_PCT_MIN


def detect(df: pd.DataFrame) -> pd.Series:
    """外側三黑 — 創新高紅 K + 連三黑 K (無跳空) + 跌破紅 K 低點.

    Conditions (PATTERN_INVENTORY P15):
      1. D-3: 創新高紅 K (close > prior_high_60 AND is_red)
      2. D-2, D-1, D-0: 連三黑 K (is_black × 3)
      3. D-2 與 D-1 之間無向下跳空 (high_{D-1} >= low_{D-2})
      4. 今日 close < D-3 之 low (跌破紅 K 低點)
      5. 唯一「高檔長黑」場合保留 body 門檻 — D-0 body_pct >= 0.04
    """
    g = df.groupby("ticker")
    close_d3 = g["close"].shift(3)
    open_d3 = g["open"].shift(3)
    high_d3 = g["high"].shift(3)
    low_d3 = g["low"].shift(3)
    prior_high_60_d3 = g["prior_high_60"].shift(3)
    d3_red_new_high = (close_d3 > open_d3) & (close_d3 > prior_high_60_d3)

    close_d2 = g["close"].shift(2)
    open_d2 = g["open"].shift(2)
    low_d2 = g["low"].shift(2)
    close_d1 = g["close"].shift(1)
    open_d1 = g["open"].shift(1)
    high_d1 = g["high"].shift(1)

    d2_black = close_d2 < open_d2
    d1_black = close_d1 < open_d1
    d0_black = df["close"] < df["open"]

    no_gap_d2_d1 = high_d1 >= low_d2

    breaks_d3_low = df["close"] < low_d3

    d0_body_pct = (df["open"] - df["close"]).abs() / df["open"].replace(0, float("nan"))
    high_long_black = d0_body_pct >= HIGH_LONG_BLACK_BODY_PCT_MIN

    return (
        d3_red_new_high & d2_black & d1_black & d0_black & no_gap_d2_d1
        & breaks_d3_low & high_long_black
    ).fillna(False)
