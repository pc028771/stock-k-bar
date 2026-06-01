"""咬定型態 — context_only / entry-support (多方咬定可作主力大「整理完突破」訊號).

Course source: 第 24 篇《咬定型態》(A5C5E3F242DCE38F0E9061E3FBC85B81)
Cross-course definition: PATTERN_INVENTORY P25.
Engineering proxy constants: NARROW_CONSOLIDATION_BARS, NARROW_CONSOLIDATION_RANGE_MAX.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import (
    NARROW_CONSOLIDATION_BARS,
    NARROW_CONSOLIDATION_RANGE_MAX,
)


def detect(df: pd.DataFrame) -> pd.Series:
    """多方咬定 OR 空方咬定 — 狹幅整理後力量型 K 突破/跌破.

    Conditions (PATTERN_INVENTORY P25):
      多方咬定:
        1. 過去 N 根 (NARROW_CONSOLIDATION_BARS) K 線狹幅整理:
           (max(high) - min(low)) / mean(close) < 3%
        2. 今日紅 K
        3. close > 整理區高點

      空方咬定: 反相 — 今日黑 K + close < 整理區低點.
    """
    N = NARROW_CONSOLIDATION_BARS
    g = df.groupby("ticker")

    # 過去 N 天 (D-N .. D-1) 的 high/low/close — transform 保留 df.index 對齊
    past_high_max = g["high"].transform(lambda s: s.shift(1).rolling(N, min_periods=N).max())
    past_low_min = g["low"].transform(lambda s: s.shift(1).rolling(N, min_periods=N).min())
    past_close_mean = g["close"].transform(lambda s: s.shift(1).rolling(N, min_periods=N).mean())
    narrow = (past_high_max - past_low_min) / past_close_mean.replace(0, float("nan")) < NARROW_CONSOLIDATION_RANGE_MAX

    is_red = df["close"] > df["open"]
    is_black = df["close"] < df["open"]

    bull_bite = narrow & is_red & (df["close"] > past_high_max)
    bear_bite = narrow & is_black & (df["close"] < past_low_min)

    return (bull_bite | bear_bite).fillna(False)
