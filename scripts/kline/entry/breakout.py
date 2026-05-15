"""Breakout attack entry signal — pure course definition.

Course source: 【突破跌破】突破意義的釐清, 【買點賣點】股價的買點決策(三)多頭買在攻擊

> 「對於K線圖來說，價格才是最重要的事情，不需要加上成交量」
> 「與這一根突破的K線是否長紅、有沒有上影線都無關」

This implementation deliberately does NOT include:
  - is_red filter
  - close_pos threshold
  - volume_ratio threshold

Those are non-course filters; see kline/extras/strict_breakout.py if desired.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = breakout attack entry signal on that bar.

    Required df columns: close, prior_high_60, ma60.
    """
    return (
        (df["close"] > df["prior_high_60"])
        & df["ma60"].notna()
        & (df["close"] > df["ma60"])
    ).fillna(False)
