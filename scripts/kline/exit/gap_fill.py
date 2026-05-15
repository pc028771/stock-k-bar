"""Attack gap fill exit signal — E1.

Course source: 【買點賣點】出場點的各種依據(二).

Definition: if a stock gaps up materially more than the market (excess gap),
that gap is interpreted as an "attack gap" (urgency buying at any price).
When that gap is filled — i.e., the same day's close falls below the prior
close — the attack is invalidated and we exit.

Required df columns: open, close, prev_close, market_open_ret.
  market_open_ret = (TAIEX open / TAIEX prev close - 1) on that bar's date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EXCESS_GAP_MIN = 0.02  # 2% excess gap threshold


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = gap fill triggered on that bar.

    `entries` is accepted for interface uniformity but not used (this
    condition does not need entry context).
    """
    prev_close = df["prev_close"].replace(0, np.nan)
    stock_gap = df["open"] / prev_close - 1
    excess_gap = stock_gap - df["market_open_ret"].fillna(0.0)
    triggered = (excess_gap >= EXCESS_GAP_MIN) & (df["close"] < df["prev_close"])
    return triggered.fillna(False)
