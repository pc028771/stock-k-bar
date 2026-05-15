"""Trailing stop exit signal — 緩慢推升型.

Course source: 【買點賣點】出場點的各種依據(二),
              【賣壓化解】K線圖的第一個研判要點.

> 「前一日低點當作停利點，有過昨高都算攻擊持續」

Vectorized implementation: per trade (delineated by entry signals within
each ticker), trailing_low = expanding max of prev_low since entry.

Required df columns: ticker, close, prev_low.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series) -> pd.Series:
    """Returns bool Series. True = close fell below the trailing reference."""
    trade_id = entries.groupby(df["ticker"]).cumsum()
    trade_id = trade_id.where(trade_id > 0)
    work = df.assign(_tid=trade_id)
    trailing_low = (
        work.groupby(["ticker", "_tid"])["prev_low"]
            .expanding().max()
            .reset_index(level=[0, 1], drop=True)
            .reindex(df.index)
    )
    return (df["close"] < trailing_low).fillna(False)
