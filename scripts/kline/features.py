"""Derived features for kline conditions.

Course source: features support multiple course concepts; no single article.

Input: bars DataFrame from bars.load_bars(), sorted by (ticker, trade_date).
Output: same DataFrame with derived columns added (spec §3.2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add all derived features. Pure function — returns new DataFrame."""
    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    # Previous-bar values
    df["prev_close"] = g["close"].shift(1)
    df["prev_open"] = g["open"].shift(1)
    df["prev_high"] = g["high"].shift(1)
    df["prev_low"] = g["low"].shift(1)

    # Rolling prior highs/lows (exclude today via shift)
    df["prior_high_60"] = (
        g["high"].shift(1).rolling(60, min_periods=60).max().reset_index(level=0, drop=True)
    )
    df["prior_high_20"] = (
        g["high"].shift(1).rolling(20, min_periods=20).max().reset_index(level=0, drop=True)
    )
    df["prior_low_60"] = (
        g["low"].shift(1).rolling(60, min_periods=60).min().reset_index(level=0, drop=True)
    )
    df["prior_low_20"] = (
        g["low"].shift(1).rolling(20, min_periods=20).min().reset_index(level=0, drop=True)
    )

    # Avg volume (excluding today)
    df["avg_volume_20"] = (
        g["volume"].shift(1).rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)
    )
    df["volume_ratio"] = df["volume"] / df["avg_volume_20"].replace(0, np.nan)

    # OHLC-derived
    df["range_pct"] = (df["high"] - df["low"]) / df["open"].replace(0, np.nan)
    df["body_abs"] = (df["close"] - df["open"]).abs()
    df["body_pct"] = df["body_abs"] / df["open"].replace(0, np.nan)
    df["close_pos"] = (df["close"] - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)

    # Shadows
    df["upper_shadow"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_shadow"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["upper_shadow_ratio"] = df["upper_shadow"] / df["body_abs"].replace(0, np.nan)
    df["lower_shadow_ratio"] = df["lower_shadow"] / df["body_abs"].replace(0, np.nan)

    # MA60 slope (5-day) and 60-day-ago close (for 扣抵 prediction)
    df["ma60_slope_5d"] = df["ma60"] / g["ma60"].shift(5) - 1
    df["ma60_rolling_off_close"] = g["close"].shift(60)

    # Scoring input: consecutive days closing above MA60 prior to today, capped at 20.
    above_ma60 = (df["close"] > df["ma60"]).fillna(False).astype(int)
    df["pre_breakout_trend_days"] = (
        above_ma60.groupby(df["ticker"])
        .shift(1)
        .fillna(0)
        .groupby(df["ticker"])
        .rolling(20, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
        .astype(int)
    )

    # Scoring input: count of swing-high peaks above current close in trailing 240 days.
    # A peak at bar k is defined as high[k] == max(high[k-4:k+1]) (5-bar local max).
    # We iterate over lags 1..240 (shifted window, excludes today) and accumulate.
    LOOKBACK = 240
    n = len(df)
    peak_count = np.zeros(n, dtype=float)
    close_today = df["close"].to_numpy()
    for lag in range(1, LOOKBACK + 1):
        past_high = g["high"].shift(lag).to_numpy()
        past_max5 = (
            g["high"]
            .shift(lag)
            .rolling(5, min_periods=5)
            .max()
            .reset_index(level=0, drop=True)
            .to_numpy()
        )
        is_peak = (past_high == past_max5) & ~np.isnan(past_max5)
        peak_count += ((past_high > close_today) & is_peak).astype(float)
    has_history = g.cumcount().to_numpy() >= 20
    df["overhead_supply_layer"] = np.where(has_history, peak_count, np.nan)

    # K-line color
    df["is_red"] = df["close"] > df["open"]
    df["is_black"] = df["close"] < df["open"]
    df["is_doji"] = (df["body_pct"] <= 0.006) & (df["range_pct"] >= 0.015)

    # Pattern breakout detection
    # Course source: 型態學 03-箱型整理 + 行進ing 事件十 操作的開始與結束
    # Course requires: 「2.5–3 個月之久的整理區間，波動並未呈現越來越高或者越來越低」
    #
    # Implementation note (NOT course-stated):
    #   INTEGRATION_RANGE_MAX = 0.15 is a proxy threshold. The course describes
    #   "箱型" by shape (no rising/falling tendency) but doesn't specify exact %.
    #   15% is a pragmatic value; a future course-shape test (linear slope ≈ 0)
    #   would be more course-faithful.
    INTEGRATION_DAYS = 60  # ~3 months (course-stated)
    INTEGRATION_RANGE_MAX = 0.15  # IMPLEMENTATION PROXY — NOT course-stated

    # Compute box range over past 60 trading days (excluding today)
    prior_max_high = (
        g["high"].shift(1).rolling(INTEGRATION_DAYS, min_periods=INTEGRATION_DAYS).max()
        .reset_index(level=0, drop=True)
    )
    prior_min_low = (
        g["low"].shift(1).rolling(INTEGRATION_DAYS, min_periods=INTEGRATION_DAYS).min()
        .reset_index(level=0, drop=True)
    )

    # Range = (max - min) / min  (relative range)
    prior_range_pct = (prior_max_high - prior_min_low) / prior_min_low.replace(0, np.nan)

    # Box if range <= 15%
    df["is_in_60day_box"] = (prior_range_pct <= INTEGRATION_RANGE_MAX).fillna(False)

    # Pattern breakout: past 60 days formed a box + today's close > prior_high_60 + above ma60
    df["is_pattern_breakout"] = (
        df["is_in_60day_box"]
        & (df["close"] > df["prior_high_60"])
        & df["ma60"].notna()
        & (df["close"] > df["ma60"])
    ).fillna(False)

    return df
