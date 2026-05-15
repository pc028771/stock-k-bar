"""跳空反轉 (Gap reversal) — 3-bar bearish gap reversal.

Course source: K線行進ing 跳空篇(四) + 多空轉折組合K線 跳空反轉

Structure:
  K-2: long red K OR red K making new high
  K-1: black K with close < K-2's close
  K0:  open gaps down below K-1.low
"""
from __future__ import annotations

import pandas as pd

LONG_RED_BODY_MIN = 0.03


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    g = df.groupby("ticker")

    # K-2: long red OR new high red
    k2_is_red = g["close"].shift(2) > g["open"].shift(2)
    k2_open = g["open"].shift(2)
    k2_body = (g["close"].shift(2) - k2_open) / k2_open.replace(0, float("nan"))
    k2_is_long = k2_body >= LONG_RED_BODY_MIN
    if "prior_high_60" in df.columns:
        k2_new_high = g["high"].shift(2) >= g["prior_high_60"].shift(2)
    else:
        k2_new_high = pd.Series(False, index=df.index, dtype=bool)
    k2_qualifies = k2_is_red & (k2_is_long | k2_new_high)

    # K-1: black, close < K-2 close
    k1_is_black = g["close"].shift(1) < g["open"].shift(1)
    k1_close_below = g["close"].shift(1) < g["close"].shift(2)

    # K0: gap down
    k0_gap_down = df["open"] < g["low"].shift(1)

    return (k2_qualifies & k1_is_black & k1_close_below & k0_gap_down).fillna(False)
