"""High-zone long black — bearish signal at top.

Course source: K線行進ing 黑K篇(二) 高檔長黑 + 事件(九) 壓力現象.

> 高檔（拉抬過後）出現長黑K → 視為獲利了結賣壓 → 出場
> 不必有吞噬條件——只要高檔長黑就是訊號

Definition:
  - "High zone" = past 60 days have seen significant range expansion
    (rolling_max(high) / rolling_min(low) >= 1.3 in prior 60 bars)
  - Today is a long black K (body >= 4%)

Required df columns: ticker, open, close, high, low.
"""
from __future__ import annotations

import pandas as pd

HIGH_ZONE_RANGE_MIN = 1.3  # rolling 60-day high/low ratio
LONG_BLACK_BODY_MIN = 0.04


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = high-zone long black on that bar.

    Required df columns: ticker, open, close, high, low.
    """
    g = df.groupby("ticker")

    # Rolling 60-day high/low — exclude today (shift by 1 before rolling)
    prior_max_high = (
        g["high"].shift(1).rolling(60, min_periods=60).max()
        .reset_index(level=0, drop=True)
    )
    prior_min_low = (
        g["low"].shift(1).rolling(60, min_periods=60).min()
        .reset_index(level=0, drop=True)
    )

    is_high_zone = (
        prior_max_high / prior_min_low.replace(0, float("nan"))
    ) >= HIGH_ZONE_RANGE_MIN

    body_pct = (df["open"] - df["close"]) / df["open"].replace(0, float("nan"))
    is_long_black = (df["close"] < df["open"]) & (body_pct >= LONG_BLACK_BODY_MIN)

    return (is_high_zone & is_long_black).fillna(False)
