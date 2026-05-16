"""Dark double star (暗夜雙星) — E2.

Course source: K線行進ing 關鍵K線×轉折 + 多空轉折組合K線 dark double star.

> 長黑摜破兩根形狀相似的併排紅K線（高檔位置）

Structure (audit C6 fix — added red-K and top-zone prerequisites):
  K-2, K-1: two prior bars
    - similar shape (高低點接近、實體類似)
    - BOTH are red K (course shows red K, not generic K)
    - at top zone: (K-1.high OR K-2.high) >= prior_high_60.shift(2)
                   OR overhead_supply_layer at K-1 == 0 (clean new high)
  K0 (today): long black K (body >= 4%) whose close falls below
              min(K-1.low, K-2.low) — 摜破併排

Required df columns: ticker, open, high, low, close.
Optional df columns (for top-zone gate): prior_high_60, overhead_supply_layer.
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
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev2_open = g["open"].shift(2)
    prev2_close = g["close"].shift(2)

    # Similarity: K-1 and K-2 have similar high and similar low
    high_ratio = (prev_high - prev2_high).abs() / prev2_high.replace(0, float("nan"))
    low_ratio = (prev_low - prev2_low).abs() / prev2_low.replace(0, float("nan"))
    similar_pair = (high_ratio <= SIMILARITY_TOLERANCE) & (low_ratio <= SIMILARITY_TOLERANCE)

    # Course: both K-1 and K-2 are red K (close > open)
    k1_is_red = prev_close > prev_open
    k2_is_red = prev2_close > prev2_open
    both_red = k1_is_red & k2_is_red

    # Top-zone gate: the pair sits at a new-high / overhead-clear zone.
    # Use prior_high_60 evaluated at K-1's bar (shifted by 1) as the reference;
    # the pair counts as "at top" when either bar's high reached that level,
    # OR overhead_supply_layer at K-1 is 0 (no supply above).
    if "prior_high_60" in df.columns:
        prior_high_60_at_k1 = g["prior_high_60"].shift(1)
        at_top_price = (prev_high >= prior_high_60_at_k1) | (prev2_high >= prior_high_60_at_k1)
    else:
        at_top_price = pd.Series(False, index=df.index)

    if "overhead_supply_layer" in df.columns:
        clean_overhead_at_k1 = g["overhead_supply_layer"].shift(1).fillna(1) <= 0
    else:
        clean_overhead_at_k1 = pd.Series(False, index=df.index)

    at_top_zone = at_top_price | clean_overhead_at_k1

    # Today: long black K
    is_black = df["close"] < df["open"]
    body_pct = (df["open"] - df["close"]) / df["open"].replace(0, float("nan"))
    long_body = body_pct >= MIN_BODY_PCT

    # 摜破 = close < lower of the two prior lows
    breaks_below_pair = df["close"] < pd.concat([prev_low, prev2_low], axis=1).min(axis=1)

    return (
        similar_pair & both_red & at_top_zone & is_black & long_body & breaks_below_pair
    ).fillna(False)
