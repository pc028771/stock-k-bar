"""EXTRA: Strict-breakout filter (NOT in course).

The course explicitly says breakout entry does NOT require:
  - red K
  - close_pos threshold
  - volume ratio threshold

This filter is provided for users who want to ADD those restrictions on
top of the pure breakout signal. Default usage: disabled.

Course stance: see 【突破跌破】突破意義的釐清 — "價格才是最重要的事情，
不需要加上成交量" and "與這一根突破的K線是否長紅...都無關".
"""
from __future__ import annotations

import pandas as pd

MIN_CLOSE_POS = 0.7
MIN_VOLUME_RATIO = 1.2


def filter(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = bar passes all strict filters."""
    return (
        df["is_red"]
        & (df["close_pos"] >= MIN_CLOSE_POS)
        & (df["volume_ratio"] >= MIN_VOLUME_RATIO)
    ).fillna(False)
