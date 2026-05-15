"""Dark double star (暗夜雙星) reversal pattern — E2.

Course source: 【買點賣點】出場點(二)轉折組合K線運用出場.

Definition (intro-course implementation):
  - Black K (close < open)
  - Opens below prior bar's low
  - Body >= 4% of open

Required df columns: open, close, prev_low.
"""
from __future__ import annotations

import pandas as pd

MIN_BODY_PCT = 0.04


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = dark double star triggered on that bar."""
    is_black = df["close"] < df["open"]
    gap_below_prev_low = df["open"] < df["prev_low"]
    body_pct = (df["open"] - df["close"]) / df["open"].replace(0, float("nan"))
    long_body = body_pct >= MIN_BODY_PCT
    return (is_black & gap_below_prev_low & long_body).fillna(False)
