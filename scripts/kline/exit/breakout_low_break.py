"""Breakout bar low break exit signal — E4.

Course source: 【單一K線】紅色誤解：連續紅K的判斷要點.

> 「突破K的低點被跌破 → 攻擊假設失效 → 停損」

## Audit I8: sequential pairing with breakout_price_break

Course (紅K篇五) treats breakout_low_break as the LATER, more-permissive
attack-failure stop — it applies AFTER the early window in which
breakout_price_break (close < prior_high_60) is the relevant pivot.

We gate this exit by `bars_since_entry > BREAKOUT_PRICE_BREAK_WINDOW`:
within the early window only breakout_price_break is armed; afterward
only breakout_low_break is armed. Proxy: 2-bar window is course-not-stated.

Required df columns: ticker, low, close.
entries: bool Series marking the entry bar; the low of that bar is the
         reference. If multiple entries occur in one ticker, the latest
         entry's low is used (earlier trades should already have exited).
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import BREAKOUT_PRICE_BREAK_WINDOW
from .breakout_price_break import _bars_since_entry


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close < entry-bar low AFTER early window."""
    entry_low_at_signal = df["low"].where(entries)
    entry_low = entry_low_at_signal.groupby(df["ticker"]).ffill()

    bars_since_entry = _bars_since_entry(df, entries)
    after_window = bars_since_entry > BREAKOUT_PRICE_BREAK_WINDOW

    return ((df["close"] < entry_low) & after_window).fillna(False)
