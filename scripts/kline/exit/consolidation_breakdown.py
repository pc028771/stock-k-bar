"""中樞型態跌破 exit signal — consolidation broken to the downside.

Course source: 型態學 06-中樞型態 (下降中樞 警示型).

> 「本應上升卻長時間中樞 → 一根黑K跌出中樞範圍 → 等於整理區間被跌破」

Definition:
  - Stock entered a narrow consolidation zone in the past CONSOLIDATION_DAYS bars
  - Consolidation = (max(high) - min(low)) / mean(close) < CONSOLIDATION_RANGE_MAX
  - Today is a black K with close < min(low) over the consolidation window

This is a high-quality exit because consolidation breakdown after a held
trade signals the trend has changed (not just a temporary dip).

Required df columns: ticker, close, low, high, open.
"""
from __future__ import annotations

import pandas as pd

CONSOLIDATION_DAYS = 10                # 1-2 weeks
CONSOLIDATION_RANGE_MAX = 0.08          # 8% range = narrow


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = consolidation breakdown on that bar."""
    g = df.groupby("ticker", group_keys=False)

    # Prior N-day high/low/mean — re-index to df.index to survive filtered subsets
    prior_max = pd.Series(
        g["high"].shift(1).rolling(CONSOLIDATION_DAYS, min_periods=CONSOLIDATION_DAYS).max()
        .reset_index(level=0, drop=True).values,
        index=df.index,
    )
    prior_min = pd.Series(
        g["low"].shift(1).rolling(CONSOLIDATION_DAYS, min_periods=CONSOLIDATION_DAYS).min()
        .reset_index(level=0, drop=True).values,
        index=df.index,
    )
    prior_mean = pd.Series(
        g["close"].shift(1).rolling(CONSOLIDATION_DAYS, min_periods=CONSOLIDATION_DAYS).mean()
        .reset_index(level=0, drop=True).values,
        index=df.index,
    )

    # Was the prior N-day window narrow?
    range_pct = (prior_max - prior_min) / prior_mean.replace(0, float("nan"))
    was_consolidating = range_pct <= CONSOLIDATION_RANGE_MAX

    # Today is black K + close below prior consolidation low
    is_black = df["close"] < df["open"]
    breaks_below = df["close"] < prior_min

    return (was_consolidating & is_black & breaks_below).fillna(False)
