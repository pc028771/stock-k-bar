"""雙鴉躍空 (Two crows) — 3-bar bearish gap reversal at top.

Course source: K線行進ing 跳空篇(四) + 多空轉折組合K線 雙鴉躍空

Structure:
  K-2: at overhead pressure zone, gap-up open then close black
       (open > K-3.high) and (close < open)
  K-1: small black K
  K0:  open gaps down below K-1.low
"""
from __future__ import annotations

import pandas as pd

SMALL_BODY_MAX = 0.02


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    if "overhead_supply_layer" not in df.columns:
        return pd.Series(False, index=df.index, dtype=bool)

    g = df.groupby("ticker")

    # K-2 conditions
    k2_at_pressure = g["overhead_supply_layer"].shift(2).fillna(0) >= 1
    k2_gap_up = g["open"].shift(2) > g["high"].shift(3)
    k2_is_black = g["close"].shift(2) < g["open"].shift(2)

    # K-1: small black K
    k1_open = g["open"].shift(1)
    k1_close = g["close"].shift(1)
    k1_is_black = k1_close < k1_open
    k1_body_pct = (k1_open - k1_close).abs() / k1_open.replace(0, float("nan"))
    k1_small = k1_body_pct < SMALL_BODY_MAX

    # K0: open gap down
    k0_gap_down = df["open"] < g["low"].shift(1)

    signal = k2_at_pressure & k2_gap_up & k2_is_black & k1_is_black & k1_small & k0_gap_down
    return signal.fillna(False)
