"""鑷頂突破 entry signal — tweezer top with breakout confirmation.

Course source: 型態學 18-鑷頂與鑷底的理論學習.

Structure (course-aligned):
  - Past N consecutive K-lines have similar highs (within tolerance)
  - Today's close breaks above the common high
  - Position: "剛/即將創新高" → enforced via clean_overhead requirement
  - Above MA60 (multi background)

Important: per analysis (docs/analysis/2026-05-16-tweezer-vs-pattern.md),
adding clean_overhead enforces the course's implicit "剛創新高" position
requirement that was missing in the v1 implementation.

"沒突破之前不能靠猜" — the signal ONLY fires on the breakout day.
Tweezer formation alone is not an entry.

Required df columns: ticker, close, high, low, prior_high_60, ma60,
                      overhead_supply_layer, unfilled_gap_down_count_240d,
                      is_in_breakdown_pattern.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TWEEZER_LOOKBACK = 5            # Look at past N bars for similar highs
TWEEZER_MIN_COUNT = 2            # At least 2 K-lines must have similar highs
TWEEZER_HIGH_TOLERANCE = 0.02    # Highs within 2% considered "same"


def detect(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = tweezer top breakout on that bar.

    Per-ticker vectorized: for each bar, check if past TWEEZER_LOOKBACK bars
    contain >= TWEEZER_MIN_COUNT highs within tolerance of each other, then
    check if today's close breaks above that "tweezer high" price.

    v2: adds clean_overhead requirement to enforce the course's implicit
    "剛創新高" position (突破型態應在上方無套牢時才成立).
    """
    g = df.groupby("ticker", group_keys=False)

    # The "tweezer high" candidate = the highest of past N bars (excluding today)
    prior_max_high = (
        g["high"].shift(1)
        .rolling(TWEEZER_LOOKBACK, min_periods=TWEEZER_LOOKBACK)
        .max()
        .reset_index(level=0, drop=True)
    )

    # Count how many of past N highs are within tolerance of prior_max_high
    # We need at least TWEEZER_MIN_COUNT to qualify as tweezer

    # For each bar i, check past TWEEZER_LOOKBACK highs vs prior_max_high
    n = len(df)
    similar_count = np.zeros(n, dtype=float)
    prior_max_arr = prior_max_high.replace(0, np.nan).to_numpy()
    for lag in range(1, TWEEZER_LOOKBACK + 1):
        past_high_lag = g["high"].shift(lag).to_numpy()
        # Within tolerance of prior_max_high
        diff_pct = np.abs(past_high_lag - prior_max_arr) / prior_max_arr
        in_tolerance = diff_pct <= TWEEZER_HIGH_TOLERANCE
        similar_count += np.where(np.isnan(diff_pct), 0.0, in_tolerance.astype(float))

    has_tweezer = similar_count >= TWEEZER_MIN_COUNT

    # Today's close breaks above the tweezer high
    breaks_tweezer = df["close"] > prior_max_high

    # Near new-high zone (tweezer high near prior 60d max)
    near_new_high = (
        df["prior_high_60"].notna()
        & (prior_max_high >= df["prior_high_60"] * 0.85)  # tweezer high near prior 60d max
    )

    # Multi background
    above_ma60 = df["ma60"].notna() & (df["close"] > df["ma60"])

    # Clean overhead (course-aligned: "剛創新高" position requirement)
    # Triple-sourced: 型態學 08-騙線型態 + 行進ing 24-跳空篇三 + 入門 賣壓化解
    # (same definition used by pattern_breakout_only / is_pattern_breakout)
    if "unfilled_gap_down_count_240d" in df.columns:
        is_clean_overhead = (
            (df["overhead_supply_layer"].fillna(0) <= 0)
            & (df["unfilled_gap_down_count_240d"].fillna(0) <= 0)
        )
    else:
        is_clean_overhead = df["overhead_supply_layer"].fillna(0) <= 0

    # Exclude breakdown
    if "is_in_breakdown_pattern" in df.columns:
        not_breakdown = ~df["is_in_breakdown_pattern"].fillna(False)
    else:
        not_breakdown = pd.Series(True, index=df.index)

    return (
        pd.Series(has_tweezer, index=df.index)
        & breaks_tweezer
        & near_new_high
        & above_ma60
        & is_clean_overhead
        & not_breakdown
    ).fillna(False)
