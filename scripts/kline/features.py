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

    # 破底型態 detection
    # Course source: 型態學 16-破底型態 (pseudocode at end of the article)
    #
    # Implementation note (proxy):
    #   The course's own pseudocode uses `low < prior_low_20` as the "new-low"
    #   event signal. This is a coarse proxy for "破前低 / swing low":
    #   strictly speaking, "前低" means the previous swing low (local minimum),
    #   but the course defines this computationally as breaking the rolling 20-day
    #   prior min. We follow the course's exact pseudocode.
    #
    # Definition: >= 2 new-low events in past 60 days AND MA60 declining.
    #
    # Course rule: automatically exclude from scanner candidacy.
    # Reason: layered supply + no way to clear without absent reason or trend change.
    # Course quote: 「離最近壓力越過、或空方趨勢結束之前，都不能有摸底的想法」
    #
    # A "new-low event" = today's low broke the 20-day prior swing low.
    # BREAKDOWN_THRESHOLD = 2 implements 「不只一次」(more than once → ≥ 2).

    BREAKDOWN_WINDOW = 60          # ~3 months lookback
    BREAKDOWN_THRESHOLD = 2        # course says "不只一次" = more than once ≥ 2

    new_low_event = df["low"] < df["prior_low_20"]
    new_low_count_60d = (
        new_low_event
        .groupby(df["ticker"])
        .rolling(BREAKDOWN_WINDOW, min_periods=BREAKDOWN_WINDOW)
        .sum()
        .reset_index(level=0, drop=True)
    )
    df["new_low_count_60d"] = new_low_count_60d

    is_ma60_down = df["ma60_slope_5d"].fillna(0) < 0

    df["is_in_breakdown_pattern"] = (
        (new_low_count_60d >= BREAKDOWN_THRESHOLD)
        & is_ma60_down
    ).fillna(False)

    # === Pattern breakout — course-faithful 起點 detection ===
    # Course source: 型態學 03-箱型整理 + 14-推升攻擊 + 05-三角收斂 + 行進ing 事件十.
    #
    # Definition (course-aligned):
    #   主力收貨的整理型態 = 低點漸漸墊高 + 上緣穩定（壓力線）
    #   Breakout above the stable upper boundary = TRUE pattern breakout = 起點
    #
    # NOT: a "sleeping" flat-range stock (those have no rising lows).
    #
    # Detection (60-day window):
    #   A. 低點墊高 (Rising lows) — at least HALF of the 60-day window's lows
    #      are higher than their predecessor (consistent accumulation direction).
    #   B. 上緣穩定 (Stable upper boundary) — the spread of the 60-day rolling-max-of-highs
    #      is constrained (i.e., the upper boundary doesn't trend up much — a "ceiling").
    #   C. Today breaks above that ceiling (close > prior_high_60).
    #   D. Above ma60 (multi background) — already required.

    INTEGRATION_DAYS = 60  # ~3 months (course-stated)

    # === A. Rising lows count ===
    # How many days in past 60 had higher_low (low > prev_low)?
    # Course-aligned threshold: at least HALF the bars must be rising-low.
    higher_low_indicator = (df["low"] > df["prev_low"]).astype(int)
    df["higher_low_count_60d"] = (
        higher_low_indicator
        .groupby(df["ticker"])
        .rolling(INTEGRATION_DAYS, min_periods=INTEGRATION_DAYS)
        .sum()
        .reset_index(level=0, drop=True)
    )
    RISING_LOWS_MIN = INTEGRATION_DAYS // 2  # 30 of 60 days

    # === B. Stable upper boundary ===
    # The 60-day ceiling should not have risen from the first half to the second half.
    # Measured by comparing:
    #   - prior_high_60: the overall 60-day ceiling (rolling max of shift(1) over 60 bars)
    #   - prior_high_30_early: rolling max of the FIRST half (shift(31) over 30 bars)
    # Spread = (prior_high_60 - prior_high_30_early) / prior_high_60
    #   - Triangle pattern: ceiling is the same throughout → spread ≈ 0
    #   - Trending stock: early-half max << late-half max → spread is large
    prior_high_30_early = (
        g["high"].shift(31).rolling(30, min_periods=30).max()
        .reset_index(level=0, drop=True)
    )
    upper_band_spread = (
        (df["prior_high_60"] - prior_high_30_early) / df["prior_high_60"].replace(0, np.nan)
    )
    df["upper_band_spread_60d"] = upper_band_spread.fillna(1.0)
    STABLE_UPPER_MAX_SPREAD = 0.05  # Within 5% — upper boundary is stable

    # === C. is_pattern_breakout (course-faithful) ===
    # Rising lows (A) + stable upper boundary (B) + breakout above ceiling (C) + above MA60 (D)
    df["is_pattern_breakout"] = (
        (df["higher_low_count_60d"] >= RISING_LOWS_MIN)
        & (df["upper_band_spread_60d"] <= STABLE_UPPER_MAX_SPREAD)
        & (df["close"] > df["prior_high_60"])
        & df["ma60"].notna()
        & (df["close"] > df["ma60"])
    ).fillna(False)

    return df
