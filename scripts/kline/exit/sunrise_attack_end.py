"""Sunrise attack end — exit when continuous sunrise breaks.

Course source: K線行進ing 紅K篇(七) 日出攻擊 + 事件(十) 操作的開始與結束.

> 還沒有結束的時候不應該出場；結束的時候不要看新聞消息。
> 日出攻擊結束 = 連續日出後第一根不再 sunrise (high <= prev_high OR low <= prev_low).

This fires AFTER a sunrise streak of at least N days has been broken.
We need to be in a sunrise context to begin with — otherwise random non-sunrise
bars would trigger spurious exits.

Required df columns: ticker, high, low, prev_high, prev_low.
"""
from __future__ import annotations

import pandas as pd

MIN_SUNRISE_BARS = 2  # need at least 2 prior sunrise bars to consider streak broken


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = sunrise streak just broke.

    Required df columns: ticker, high, low, prev_high, prev_low.
    """
    is_sunrise_today = (df["high"] > df["prev_high"]) & (df["low"] > df["prev_low"])

    # Check that all days from t-MIN_SUNRISE_BARS to t-1 were sunrise
    in_streak = pd.Series(True, index=df.index)
    for k in range(1, MIN_SUNRISE_BARS + 1):
        in_streak = in_streak & is_sunrise_today.groupby(df["ticker"]).shift(k).fillna(False)

    return (in_streak & ~is_sunrise_today).fillna(False)
