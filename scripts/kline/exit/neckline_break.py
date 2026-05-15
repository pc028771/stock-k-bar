"""Neckline break exit signal — E3.

Course source: 【買點賣點】多方操作的出場點邏輯.

Neckline proxy: prior_low_20 (precise version awaits ma60_neckline stub
replacement once K線行進ing is read).

Course rule: close-price confirmation across two consecutive days.
The exit signal fires on the confirmation day (day after first break).

Required df columns: ticker, close, prior_low_20.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = neckline break confirmed on that bar."""
    broke_today = df["close"] < df["prior_low_20"]
    broke_yesterday = broke_today.groupby(df["ticker"]).shift(1).fillna(False)
    return (broke_yesterday & broke_today).fillna(False)
