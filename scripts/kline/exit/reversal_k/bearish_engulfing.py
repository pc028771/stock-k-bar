"""空頭吞噬 (Bearish engulfing) — 獲利了結賣壓 of force exhaustion.

Course source: K線行進ing 事件(九) 壓力現象的呈現
              + 多空轉折組合K線 包覆線

Structure:
  K-1: red K (close > open)
  K0:  black K (close < open) whose body fully engulfs K-1's body
        open >= K-1.close  AND  close <= K-1.open
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    g = df.groupby("ticker")
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_is_red = prev_close > prev_open

    is_black = df["close"] < df["open"]
    engulfs = (df["open"] >= prev_close) & (df["close"] <= prev_open)

    return (prev_is_red & is_black & engulfs).fillna(False)
