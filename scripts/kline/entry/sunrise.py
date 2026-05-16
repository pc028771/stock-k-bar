"""日出攻擊 entry signal — sunrise attack.

Course source: K線行進ing 紅K篇(七) 日出攻擊
              + K線行進ing 事件(十) 操作的開始與結束

Definition:
  日出 = K線的高點與低點都比前一日高 (high > prev_high AND low > prev_low)
  日出攻擊 = 突破新高之後 + 連續 N 天日出

Two sub-types:
  漂亮的日出攻擊: body widens each day (strong attack)
  醜陋的日出攻擊: body shrinks each day (warning — may devolve into 大敵當前)

This implementation detects the START of sunrise attack:
- breakout_attack triggered 2 bars ago (close > prior_high_60 AND close > ma60)
- AND 2 consecutive sunrise bars after the breakout (today + yesterday)

SUNRISE_BARS_REQUIRED = 2 refers to the 2 confirmation bars AFTER the breakout.
The breakout bar itself is not required to be a sunrise bar.
"""
from __future__ import annotations

import pandas as pd

SUNRISE_BARS_REQUIRED = 2  # confirmation bars after breakout


def detect(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = sunrise attack confirmed on that bar.

    Required df columns: ticker, high, low, close, prev_high, prev_low,
                          prior_high_60, ma60, is_in_breakdown_pattern.

    Course exclusion: stocks in 破底型態 are excluded (型態學 16).
    """
    g = df.groupby("ticker")

    # Sunrise per-bar: both H and L strictly exceed prev bar's H and L
    is_sunrise_bar = (df["high"] > df["prev_high"]) & (df["low"] > df["prev_low"])

    # Rolling sum of 2 consecutive sunrise bars (today + yesterday)
    sunrise_streak = (
        is_sunrise_bar
        .groupby(df["ticker"])
        .rolling(SUNRISE_BARS_REQUIRED, min_periods=SUNRISE_BARS_REQUIRED)
        .sum()
        .reset_index(level=0, drop=True)
    )

    # The breakout bar is 2 bars back (before the 2 confirmation bars)
    # breakout: close > prior_high_60 AND close > ma60
    breakout_was = (
        (g["close"].shift(SUNRISE_BARS_REQUIRED) > g["prior_high_60"].shift(SUNRISE_BARS_REQUIRED))
        & (g["ma60"].shift(SUNRISE_BARS_REQUIRED).notna())
        & (g["close"].shift(SUNRISE_BARS_REQUIRED) > g["ma60"].shift(SUNRISE_BARS_REQUIRED))
    )

    # Course exclusion: 破底型態 (型態學 16)
    not_in_breakdown = ~df["is_in_breakdown_pattern"].fillna(False)

    return (
        (sunrise_streak >= SUNRISE_BARS_REQUIRED) & breakout_was & not_in_breakdown
    ).fillna(False)
