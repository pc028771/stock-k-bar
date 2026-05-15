"""大敵當前 (Enemy at gate) — three reds fail to widen + long black breaks K1 midpoint.

Course source: K線行進ing 紅K篇(一) 三連紅 + 紅K篇(七) 醜陋日出
              + 多空轉折組合K線 大敵當前

Structure:
  K-3, K-2, K-1: three small red Ks (body_pct < 2%)
  K0:  long black K (body >= 3%) whose close falls below
        K-3's MIDPOINT  =  (K-3.open + K-3.close) / 2
"""
from __future__ import annotations

import pandas as pd

SMALL_BODY_MAX = 0.02
LONG_BLACK_BODY_MIN = 0.03


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    g = df.groupby("ticker")

    def _is_small_red(n: int) -> pd.Series:
        o = g["open"].shift(n)
        c = g["close"].shift(n)
        is_red = c > o
        body = (c - o).abs() / o.replace(0, float("nan"))
        return is_red & (body < SMALL_BODY_MAX)

    three_small_reds = _is_small_red(1) & _is_small_red(2) & _is_small_red(3)

    # K-3 midpoint
    k3_mid = (g["open"].shift(3) + g["close"].shift(3)) / 2

    # Today: long black breaking K-3 midpoint
    body_pct = (df["open"] - df["close"]) / df["open"].replace(0, float("nan"))
    is_long_black = (df["close"] < df["open"]) & (body_pct >= LONG_BLACK_BODY_MIN)
    breaks_mid = df["close"] < k3_mid

    return (three_small_reds & is_long_black & breaks_mid).fillna(False)
