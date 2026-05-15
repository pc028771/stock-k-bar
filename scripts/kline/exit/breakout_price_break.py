"""Breakout-price break — earlier exit than breakout_low_break.

Course source: K線行進ing 紅K篇(五) 黑K接續出現.

> 突破紅K 後接黑K，跌破突破價（prior_high_60）→ 短線交易者立即停損

This is more sensitive than `breakout_low_break` (which uses entry-bar low).
For each trade, the breakout price is the prior_high_60 at the entry bar.

Required df columns: ticker, close, prior_high_60.
entries: bool Series marking the entry bar.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close fell below the breakout price."""
    breakout_price_at_signal = df["prior_high_60"].where(entries)
    breakout_price = breakout_price_at_signal.groupby(df["ticker"]).ffill()
    return (df["close"] < breakout_price).fillna(False)
