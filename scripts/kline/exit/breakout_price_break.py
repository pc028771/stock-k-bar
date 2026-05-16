"""Breakout-price break — earlier exit than breakout_low_break.

Course source: K線行進ing 紅K篇(五) 黑K接續出現.

> 突破紅K 後接黑K，跌破突破價（prior_high_60）→ 短線交易者立即停損

This is the EARLY, more-sensitive exit for the first day(s) after entry.
For each trade, the breakout price is the prior_high_60 at the entry bar.

## Audit I8: sequential pairing with breakout_low_break

Course (紅K篇五) treats breakout_price_break as the EARLY-stage stop (the
attack must hold its breakout price immediately). breakout_low_break is
the LATER-stage stop (only after the breakout price is no longer the
relevant pivot). Previously both fired in parallel, with whichever
triggered first winning.

We now gate each by `bars_since_entry`:
  - breakout_price_break is armed only for the FIRST 2 bars after entry
    (`BREAKOUT_PRICE_BREAK_WINDOW`).
  - breakout_low_break is armed only AFTER that window (see its module).

Proxy: course says "first day or two" but doesn't number it. We use 2
bars as the default; see `course_proxy_constants.I8`.

Required df columns: ticker, close, prior_high_60.
entries: bool Series marking the entry bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..course_proxy_constants import BREAKOUT_PRICE_BREAK_WINDOW


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close < breakout price within early window."""
    breakout_price_at_signal = df["prior_high_60"].where(entries)
    breakout_price = breakout_price_at_signal.groupby(df["ticker"]).ffill()

    # bars_since_entry: 0 on the entry bar, 1 on next bar, ... Reset per trade.
    # Computed as cumulative count within ticker, minus the cumulative count at
    # the last entry. Using forward-filled "entry position" semantics.
    bars_since_entry = _bars_since_entry(df, entries)

    triggered = (df["close"] < breakout_price).fillna(False)
    in_window = (bars_since_entry >= 1) & (bars_since_entry <= BREAKOUT_PRICE_BREAK_WINDOW)
    return (triggered & in_window).fillna(False)


def _bars_since_entry(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Bars elapsed since the most recent entry within the same ticker.

    0 = entry bar itself; 1 = next bar; etc. NaN before any entry.
    """
    # Cumulative count per ticker (0, 1, 2, ...).
    g = df.groupby("ticker", group_keys=False)
    cum = g.cumcount()
    # Cum-count value AT the entry bar, forward-filled to subsequent bars.
    entry_cum = pd.Series(np.where(entries.to_numpy(), cum.to_numpy(), np.nan), index=df.index)
    entry_cum = entry_cum.groupby(df["ticker"]).ffill()
    return (cum - entry_cum).astype(float)
