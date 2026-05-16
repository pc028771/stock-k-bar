"""上肩缺口拉回承接 entry signal — only course-approved pullback entry.

Course source: 型態學 17-上下肩缺口的理論學習.

> 「股價剛剛第一次型態突破之後不久，隔日跳空向上，再隔日黑K並且呈現日落的現象，
>  但是缺口並未被回補。」

3-bar structure (signal fires on K0 = today):
  K-2: First-time pattern breakout red K (close > prior_high_60 AND red K
       AND is_pattern_breakout)
  K-1: Gap-up red K (open > K-2.high AND red K)
  K0:  Sundown black K (high < K-1.high AND low < K-1.low AND black K)
       AND gap is NOT filled (low > K-2.close)

Per course: this is a 洗盤/誘空 setup where short-term traders dump and
shorts try to fade — the gap will hold and price will resume.

Stop loss: gap lower bound = K-2.close.

Background: course says non-明顯多頭 environment (we don't enforce this
in the system; user can filter by market regime if desired).

Required df columns: ticker, open, high, low, close, prior_high_60,
                      ma60, is_pattern_breakout.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = shoulder gap up pullback on that bar (K0)."""
    g = df.groupby("ticker", group_keys=False)

    # K-2 (two days ago): first-time pattern breakout red K
    k2_open = g["open"].shift(2)
    k2_close = g["close"].shift(2)
    k2_high = g["high"].shift(2)
    if "is_pattern_breakout" in df.columns:
        k2_is_pattern_breakout = g["is_pattern_breakout"].shift(2).fillna(False)
    else:
        k2_is_pattern_breakout = pd.Series(False, index=df.index)
    k2_is_red = k2_close > k2_open

    # K-1 (yesterday): gap-up red K
    k1_open = g["open"].shift(1)
    k1_close = g["close"].shift(1)
    k1_high = g["high"].shift(1)
    k1_low = g["low"].shift(1)
    k1_gap_up = k1_open > k2_high
    k1_is_red = k1_close > k1_open

    # K0 (today): sundown black K, gap unfilled
    today_is_black = df["close"] < df["open"]
    today_sundown = (df["high"] < k1_high) & (df["low"] < k1_low)
    gap_unfilled = df["low"] > k2_close

    # Multi background: above MA60
    above_ma60 = df["ma60"].notna() & (df["close"] > df["ma60"])

    # Exclude breakdown pattern
    if "is_in_breakdown_pattern" in df.columns:
        not_breakdown = ~df["is_in_breakdown_pattern"].fillna(False)
    else:
        not_breakdown = pd.Series(True, index=df.index)

    return (
        k2_is_pattern_breakout
        & k2_is_red
        & k1_gap_up
        & k1_is_red
        & today_is_black
        & today_sundown
        & gap_unfilled
        & above_ma60
        & not_breakdown
    ).fillna(False)
