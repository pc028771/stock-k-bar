"""Attack gap killed — exit when prior attack gap's force is消除d.

Course source: K線行進ing 跳空篇(二) 一般跳空的行進判斷.

> 當這個向下跳空把過去的攻擊跳空給消滅了，那就表示沒有攻擊意願。

Definition:
  - Attack gap = gap-up on/after entry whose lower bound is the prev_high
  - Exit when close falls below the attack gap's lower bound
    (this represents the gap being "killed")

Implementation note:
  For each trade, we track the most recent attack gap's lower bound (prev_high
  on the most recent gap-up day since entry). Exit when close < that bound.
  Using "most recent" rather than cumulative-max because a new higher attack
  gap supersedes the old one as the active support reference.

Required df columns: ticker, open, close, prev_high.
entries: bool Series marking the entry bar.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close fell below the most recent attack gap lower bound.

    Required df columns: ticker, open, close, prev_high.
    """
    # Trade-id: per-ticker cumulative count of entries (0 = before first entry)
    trade_id = entries.groupby(df["ticker"]).cumsum()

    # Days where a gap-up attack occurred: open > prev_high
    gap_up = df["open"] > df["prev_high"]

    # The lower bound of an attack gap is prev_high on that day
    gap_lower = df["prev_high"].where(gap_up)

    # Build a single composite key for groupby to avoid MultiIndex issues
    composite_key = df["ticker"].astype(str) + "__" + trade_id.astype(str)

    # Within each (ticker, trade_id) group, forward-fill the most recent
    # attack gap lower bound so every subsequent bar can compare against it.
    recent_gap_lower = (
        gap_lower.groupby(composite_key).ffill()
    )

    return (df["close"] < recent_gap_lower).fillna(False)
