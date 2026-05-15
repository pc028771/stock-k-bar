"""Trend change exit signal — 趨勢改變型.

Course source: 【買點賣點】出場點的各種依據(一).

Course says exit when the trend changes; take the HIGHER of:
  1. 末升低跌破 (last_rally_low break)
  2. 上升趨勢線跌破 (rising_trendline break)
  3. 季線下彎 (MA60 turn-down)

Intro course does not give precise detection for (1) and (2):
  - 末升低 requires swing-low detection (peaks/troughs algorithm)
  - 趨勢線 requires multi-point fitting
Both will be added later. For now we implement (3) only.

Required df columns: ticker, ma60_slope_5d.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = MA60 slope just flipped from >=0 to <0."""
    slope = df["ma60_slope_5d"]
    prev_slope = slope.groupby(df["ticker"]).shift(1)
    return ((prev_slope >= 0) & (slope < 0)).fillna(False)


def _TODO_last_rally_low(df: pd.DataFrame) -> pd.Series:
    """Pending implementation — needs swing-low detection."""
    return pd.Series(float("nan"), index=df.index)


def _TODO_rising_trendline(df: pd.DataFrame) -> pd.Series:
    """Pending implementation — needs multi-point line fitting."""
    return pd.Series(float("nan"), index=df.index)
