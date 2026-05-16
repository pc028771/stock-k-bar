"""Attack gap killed — exit when prior attack gap's force is消除d.

Course source: K線行進ing 跳空篇(二) 一般跳空的行進判斷.

> 當這個向下跳空把過去的攻擊跳空給消滅了，那就表示沒有攻擊意願。

Definition:
  - Attack gap = the FIRST gap-up after the breakout entry. Its lower bound
    is `prev_high` on that gap-up day.
  - Exit when close falls below that ORIGINAL attack-gap lower bound
    (this represents the original attack gap being "killed").

Implementation note (audit C5 fix):
  Per course (跳空篇二), the canonical "attack gap" is the FIRST gap-up
  following the breakout, not the most recent one. A subsequent smaller
  gap-up does NOT replace the reference — once the FIRST attack-gap lower
  bound is broken, the attack is over.

  Within each trade window (entries-aware), we lock the FIRST gap-up's
  prev_high and reuse it for all subsequent bars until the next entry on
  the same ticker.

Required df columns: ticker, open, close, prev_high.
entries: bool Series marking the entry bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close fell below the FIRST attack gap lower bound
    of the current trade window.

    Required df columns: ticker, open, close, prev_high.
    """
    # Trade-id: per-ticker cumulative count of entries (0 = before first entry)
    trade_id = entries.fillna(False).astype(bool).groupby(df["ticker"]).cumsum()

    # Days where a gap-up attack occurred: open > prev_high
    gap_up = (df["open"] > df["prev_high"]).fillna(False)

    # The lower bound of an attack gap is prev_high on that day; NaN otherwise.
    gap_lower = df["prev_high"].where(gap_up)

    # Build a single composite key for groupby to avoid MultiIndex issues
    composite_key = df["ticker"].astype(str) + "__" + trade_id.astype(str)

    # Within each (ticker, trade_id) group, lock the FIRST attack-gap lower bound
    # (i.e., forward-fill from the first non-NaN value within the group, but do
    # NOT let subsequent gap-ups overwrite the reference).
    #
    # Trick: within each group, take the cumulative "first non-NaN" by computing
    # group-wise cummax of (is_first_gap_lower) and using transform to broadcast.
    def _first_gap_lower(group: pd.Series) -> pd.Series:
        # First non-NaN value within the group
        valid = group.dropna()
        if valid.empty:
            return pd.Series(np.nan, index=group.index)
        first_value = valid.iloc[0]
        first_pos = valid.index[0]
        out = pd.Series(np.nan, index=group.index)
        # Lock to first_value from first_pos onward
        out.loc[first_pos:] = first_value
        return out

    first_gap_lower = gap_lower.groupby(composite_key, sort=False).transform(_first_gap_lower)

    # Only valid for bars AFTER an entry has fired (trade_id >= 1).
    in_trade = trade_id >= 1
    triggered = in_trade & (df["close"] < first_gap_lower)
    return triggered.fillna(False)
