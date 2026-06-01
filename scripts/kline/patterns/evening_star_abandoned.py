"""夜星棄嬰 — bear, exit.

Course source: 第 11 篇《夜星棄嬰》(3F9C5C8C7B81C89FBCA2970EF1855997)
Cross-course definition: PATTERN_INVENTORY P12.
"""
from __future__ import annotations

import pandas as pd

from ._common import bull_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """夜星棄嬰 — 多方力竭/遇壓 + 長紅 + 醞釀 K (doji 或短 K) + 跌破中值黑 K.

    Conditions (PATTERN_INVENTORY P12):
      1. 多方力竭/遇壓背景
      2. D-2: 紅 K (course-faithful — 不加 body 門檻, PATTERN_DEFINITIONS §1)
      3. D-1: 醞釀 K — is_doji OR body_pct < 1%
      4. D-0: close < D-2 中值 (open+close)/2
    """
    g = df.groupby("ticker")
    open_d2 = g["open"].shift(2)
    close_d2 = g["close"].shift(2)
    d2_red = close_d2 > open_d2

    d1_body_pct = g["body_pct"].shift(1).fillna(1.0)
    d1_doji = g["is_doji"].shift(1).fillna(False)
    d1_brewing = d1_doji | (d1_body_pct < 0.01)

    d2_mid = (open_d2 + close_d2) / 2
    d0_breaks_mid = df["close"] < d2_mid

    exhaust = bull_exhaustion_context(df)

    return (d2_red & d1_brewing & d0_breaks_mid & exhaust).fillna(False)
