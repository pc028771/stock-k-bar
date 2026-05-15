"""Breakout bar low break exit signal — E4.

Course source: 【單一K線】紅色誤解：連續紅K的判斷要點.

> 「突破K的低點被跌破 → 攻擊假設失效 → 停損」

Required df columns: ticker, low, close.
entries: bool Series marking the entry bar; the low of that bar is the
         reference. If multiple entries occur in one ticker, the latest
         entry's low is used (earlier trades should already have exited).
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close fell below the entry bar's low."""
    entry_low_at_signal = df["low"].where(entries)
    entry_low = entry_low_at_signal.groupby(df["ticker"]).ffill()
    return (df["close"] < entry_low).fillna(False)
