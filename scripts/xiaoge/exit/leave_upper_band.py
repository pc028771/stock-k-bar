"""xiaoge_leave_upper_band — 停利 exit rule.

Course source: ch07 04:58, ch13 02:38
> 「布林軌道打開，股價沿著上軌前進，那周圍點就是起漲點。」(ch03 01:35)
> 「K 棒一離開上軌，就找短線停利。」(ch07 04:58, ch13 02:38)

Pure course-defined exit: as long as close >= bb_upper, hold; the first
bar where close < bb_upper (after entry) triggers exit.

This is the ONLY course-defined exit. Stop loss is NOT spelled out in the
course; backtest uses this rule as both profit-take AND drawdown limit.
Structural stop loss (推測 跌破突破當天 K 棒低點) lives in xiaoge/extras/.
"""
from __future__ import annotations

import pandas as pd


def should_exit(close: float, bb_upper: float) -> bool:
    """True iff close fell below upper band (course exit trigger)."""
    if pd.isna(bb_upper):
        return False
    return close < bb_upper
