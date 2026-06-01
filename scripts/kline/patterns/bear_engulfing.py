"""空頭吞噬 — bear, exit (多單出場).

Course source: 第 02 篇《包覆線：空頭吞噬與多頭吞噬》(E79401532D60CC63B302926C2C33FB50)
Cross-course definition: PATTERN_DEFINITIONS.md §1, §2 + PATTERN_INVENTORY P02.
Engineering proxy constants: (none — pure structural).
"""
from __future__ import annotations

import pandas as pd

from ._common import bull_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """空頭吞噬 — 黑 K 實體包覆前日紅 K + 前日紅 K 有攻擊意義 + 多方力竭.

    Conditions (PATTERN_INVENTORY P02):
      1. 前一日紅 K (prev_close > prev_open)
      2. 前一日紅 K 具攻擊意義 (features.py prev_bar_had_attack_meaning)
      3. 今日黑 K 實體包覆 (open >= prev_close AND close <= prev_open)
      4. 多方力竭背景 (PATTERN_DEFINITIONS §2)

    Failure (not in detect — leave to simulator):
      後續 close > engulfing_bar_high 則此轉折意義失效.
    """
    g = df.groupby("ticker")
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_is_red = prev_close > prev_open

    is_black = df["close"] < df["open"]
    engulfs = (df["open"] >= prev_close) & (df["close"] <= prev_open)

    prev_attack_meaning = df["prev_bar_had_attack_meaning"].fillna(False)
    exhaust = bull_exhaustion_context(df)

    return (prev_is_red & is_black & engulfs & prev_attack_meaning & exhaust).fillna(False)
