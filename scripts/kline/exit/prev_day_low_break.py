"""Previous-day low break exit signal — short-term trading.

Course source: 【買點賣點】買點與攻擊研判.

> 「短線操作的停利點可以設定在昨天的低點」

Required df columns: close, prev_low.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = close < prev_low (strict)."""
    return (df["close"] < df["prev_low"]).fillna(False)
