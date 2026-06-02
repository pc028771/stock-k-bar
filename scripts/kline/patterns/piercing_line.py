"""貫穿型態 — 烏雲罩頂 (bear) + 曙光乍現 (bull), context_only.

Course source: 第 19 篇《貫穿型態》(53E0BA326CBB753118E3F8C6232F7F0F)
Cross-course definition: PATTERN_INVENTORY P20.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """貫穿型態 — 烏雲罩頂 OR 曙光乍現任一觸發即 True.

    烏雲罩頂 (bear, article line 38):
      1. 多方趨勢 (close > ma60 AND ma60 rising)
      2. D-1: 紅 K (course: 「漲了之後…」 implicit; no explicit new-high req)
      3. D-0: 黑 K, 開高 (open > prev_close) 但 close < D-1 中值
      4. 沒到吞噬程度 (close > prev_open)

    曙光乍現 (bull, article line 56):
      1. 空方趨勢 (close < ma60 AND ma60 falling)
         course: 「對股價已經有一定程度的悲觀時出現」
      2. D-1: 黑 K (no explicit new-low req; course says only「悲觀」, not「創新低」)
      3. D-0: 紅 K, 開低 (open < prev_close) 但 close 站上 D-1 中值
      4. 沒到吞噬程度 (close < prev_open)

    2026-06-02 update (case #2 華景電 6788 2022-01-24):
      Removed prev_new_high / prev_new_low requirements. Course defines
      trend background as「多方趨勢」/「悲觀」(captured by bull_trend /
      bear_trend), not by 60-day high/low. The new-high/low gate over-
      constrained piercing patterns that occurred within range-bound
      downtrends (華景電 close was 33% below 60-day high but not at fresh low).
    """
    g = df.groupby("ticker")
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_mid = (prev_open + prev_close) / 2

    prev_red = prev_close > prev_open
    prev_black = prev_close < prev_open

    # bull / bear trend = course's「多方趨勢」/「空方趨勢」context.
    # ma60 NaN fallback: when MA insufficient (early ticker history),
    # fall back to close vs prior_high_60 / prior_low_60 as crude proxy.
    ma60_nan = df["ma60"].isna()
    ma60_rising = df["ma60_slope_5d"].fillna(0) > 0
    ma60_falling = df["ma60_slope_5d"].fillna(0) < 0
    bull_trend = ((df["close"] > df["ma60"]) & ma60_rising) | (ma60_nan & (df["close"] >= g["prior_high_60"].shift(1) * 0.95).fillna(False))
    bear_trend = ((df["close"] < df["ma60"]) & ma60_falling) | (ma60_nan & (df["close"] <= g["prior_low_60"].shift(1) * 1.05).fillna(False))

    # Boundary tolerance — chart reading is not pixel-precise; course
    # description「貫穿中值」/「未包覆整個黑K」are inherently visual.
    # Apply 1% slack on both:
    #   - not_engulf (case #2 華景電 6788 2022-01-24): close $1 (0.5%) over
    #   - breaks_mid / above_mid (case #3 上曜 1316 2022-01-20): close 0.6%
    #     above mid still reads as「跌穿」on the chart
    is_black = df["close"] < df["open"]
    open_high = df["open"] > prev_close
    breaks_mid = df["close"] < prev_mid * 1.01  # close within 1% above mid OK
    not_engulf = df["close"] > prev_open * 0.99  # within 1% below prev_open

    dark_cloud = bull_trend & prev_red & is_black & open_high & breaks_mid & not_engulf

    is_red = df["close"] > df["open"]
    open_low = df["open"] < prev_close
    above_mid = df["close"] > prev_mid * 0.99  # close within 1% below mid OK
    not_engulf_bull = df["close"] < prev_open * 1.01  # within 1% above prev_open

    piercing = bear_trend & prev_black & is_red & open_low & above_mid & not_engulf_bull

    return (dark_cloud | piercing).fillna(False)
