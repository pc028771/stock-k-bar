"""貫穿型態 — 烏雲罩頂 (bear) + 曙光乍現 (bull), context_only.

Course source: 第 19 篇《貫穿型態》(53E0BA326CBB753118E3F8C6232F7F0F)
Cross-course definition: PATTERN_INVENTORY P20.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """貫穿型態 — 烏雲罩頂 OR 曙光乍現任一觸發即 True.

    烏雲罩頂 (bear):
      1. 多方趨勢 (close > ma60 AND ma60 rising)
      2. D-1: 紅 K, 創新高 (prev_close > prior_high_60.shift(1))
      3. D-0: 黑 K, 開高 (open > prev_close) 但 close < D-1 中值
      4. 沒到吞噬程度 (close > prev_open)

    曙光乍現 (bull):
      1. 空方趨勢 (close < ma60 AND ma60 falling)
      2. D-1: 黑 K, 創新低 (prev_low <= prior_low_60.shift(1))
      3. D-0: 紅 K, 開低 (open < prev_close) 但 close 站上 D-1 中值
      4. 沒到吞噬程度 (close < prev_open)
    """
    g = df.groupby("ticker")
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_low_v = g["low"].shift(1)
    prev_mid = (prev_open + prev_close) / 2
    prior_high_60_s = g["prior_high_60"].shift(1)
    prior_low_60_s = g["prior_low_60"].shift(1)

    prev_red = prev_close > prev_open
    prev_new_high = prev_close > prior_high_60_s
    prev_black = prev_close < prev_open
    prev_new_low = prev_low_v <= prior_low_60_s

    # 2026-06-02 fallback: ma60 NaN（backfill pre-context 不足）時，用 prev_new_high /
    # prev_new_low 代理「多方/空方狀態」。課程「多方狀態」字面上就是「創新高」之意。
    ma60_nan = df["ma60"].isna()
    ma60_rising = df["ma60_slope_5d"].fillna(0) > 0
    bull_trend = ((df["close"] > df["ma60"]) & ma60_rising) | (ma60_nan & prev_new_high.fillna(False))

    is_black = df["close"] < df["open"]
    open_high = df["open"] > prev_close
    breaks_mid = df["close"] < prev_mid
    not_engulf = df["close"] > prev_open

    dark_cloud = bull_trend & prev_red & prev_new_high & is_black & open_high & breaks_mid & not_engulf

    ma60_falling = df["ma60_slope_5d"].fillna(0) < 0
    bear_trend = ((df["close"] < df["ma60"]) & ma60_falling) | (ma60_nan & prev_new_low.fillna(False))

    is_red = df["close"] > df["open"]
    open_low = df["open"] < prev_close
    above_mid = df["close"] > prev_mid
    not_engulf_bull = df["close"] < prev_open

    piercing = bear_trend & prev_black & prev_new_low & is_red & open_low & above_mid & not_engulf_bull

    return (dark_cloud | piercing).fillna(False)
