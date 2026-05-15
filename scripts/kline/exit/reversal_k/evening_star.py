"""夜星棄嬰 (Abandoned evening star) — 3-bar bearish reversal at top.

Course source: K線行進ing 關鍵K線×轉折 + 多空轉折組合K線 夜星棄嬰

Structure:
  K-2: red K at overhead pressure zone (overhead_supply_layer >= 1)
  K-1: doji (small body, sizable range)
  K0:  long black K whose close falls below K-2's midpoint
"""
from __future__ import annotations

import pandas as pd

LONG_BLACK_BODY_MIN = 0.03


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    if "overhead_supply_layer" not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)
    if "is_doji" not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)

    g = df.groupby("ticker")

    # K-2: red at pressure
    k2_is_red = g["close"].shift(2) > g["open"].shift(2)
    k2_at_pressure = g["overhead_supply_layer"].shift(2).fillna(0) >= 1

    # K-1: doji
    k1_is_doji = g["is_doji"].shift(1).fillna(False)

    # K-2 midpoint
    k2_mid = (g["open"].shift(2) + g["close"].shift(2)) / 2

    # Today: long black breaks K-2 midpoint
    body_pct = (df["open"] - df["close"]) / df["open"].replace(0, float("nan"))
    is_long_black = (df["close"] < df["open"]) & (body_pct >= LONG_BLACK_BODY_MIN)
    breaks_mid = df["close"] < k2_mid

    return (k2_is_red & k2_at_pressure & k1_is_doji & is_long_black & breaks_mid).fillna(False)
