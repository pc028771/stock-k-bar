"""Dark double star (暗夜雙星) — E2.

Course source: K線行進ing 關鍵K線×轉折 + 多空轉折組合K線 dark double star.

> 長黑摜破兩根形狀相似的併排K線

Structure:
  K-2, K-1: two prior bars with similar shape (高低點接近、實體類似)
  K0 (today): long black K (body >= 4%) whose close falls below
              min(K-1.low, K-2.low) — 摜破併排
"""
from __future__ import annotations

import pandas as pd

MIN_BODY_PCT = 0.04
SIMILARITY_TOLERANCE = 0.03  # 3% tolerance between K-1 and K-2 highs / lows


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    g = df.groupby("ticker")

    prev_high = g["high"].shift(1)
    prev_low = g["low"].shift(1)
    prev2_high = g["high"].shift(2)
    prev2_low = g["low"].shift(2)

    # Similarity: K-1 and K-2 have similar high and similar low
    high_ratio = (prev_high - prev2_high).abs() / prev2_high.replace(0, float("nan"))
    low_ratio = (prev_low - prev2_low).abs() / prev2_low.replace(0, float("nan"))
    similar_pair = (high_ratio <= SIMILARITY_TOLERANCE) & (low_ratio <= SIMILARITY_TOLERANCE)

    # Today: long black K
    is_black = df["close"] < df["open"]
    body_pct = (df["open"] - df["close"]) / df["open"].replace(0, float("nan"))
    long_body = body_pct >= MIN_BODY_PCT

    # 摜破 = close < lower of the two prior lows
    breaks_below_pair = df["close"] < pd.concat([prev_low, prev2_low], axis=1).min(axis=1)

    return (similar_pair & is_black & long_body & breaks_below_pair).fillna(False)
