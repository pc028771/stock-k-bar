"""升降組合型態 — 上升一階 / 下降一階, context_only.

Course source: 第 25 篇《升降組合型態》(0B1DD310D7685EE74123E5147BB7CFB2)
Cross-course definition: PATTERN_INVENTORY P26.
Engineering proxy constants: NARROW_CONSOLIDATION_BARS, NARROW_CONSOLIDATION_RANGE_MAX.

與咬定型態 (P25) 的差異：升降「之前先有一根原本方向的力量 K」.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import (
    NARROW_CONSOLIDATION_BARS,
    NARROW_CONSOLIDATION_RANGE_MAX,
)

PRIOR_POWER_LOOKBACK = 20  # course-not-stated — proxy 一個月內


def detect(df: pd.DataFrame) -> pd.Series:
    """上升一階 OR 下降一階任一觸發.

    Conditions (PATTERN_INVENTORY P26):
      上升一階:
        1. 過去 20 日內出現過力量型紅 K (代理：紅 K 且 body_pct rank ≥ 0.7)
        2. 接著有 N 天狹幅整理 (P25 同條件)
        3. 今日再出現紅 K 突破整理區高點

      下降一階: 反相.
    """
    N = NARROW_CONSOLIDATION_BARS
    g = df.groupby("ticker")

    past_high_max = g["high"].transform(lambda s: s.shift(1).rolling(N, min_periods=N).max())
    past_low_min = g["low"].transform(lambda s: s.shift(1).rolling(N, min_periods=N).min())
    past_close_mean = g["close"].transform(lambda s: s.shift(1).rolling(N, min_periods=N).mean())
    narrow = (past_high_max - past_low_min) / past_close_mean.replace(0, float("nan")) < NARROW_CONSOLIDATION_RANGE_MAX

    # 過去 PRIOR_POWER_LOOKBACK 天內存在「力量型」紅 / 黑 K (用 body_pct_pct_rank_20d ≥ 0.7 + 顏色)
    pr = df["body_pct_pct_rank_20d"].fillna(0)
    power_red_today = (df["is_red"].fillna(False) & (pr >= 0.7)).astype(int)
    power_black_today = (df["is_black"].fillna(False) & (pr >= 0.7)).astype(int)
    L = PRIOR_POWER_LOOKBACK
    prior_power_red = power_red_today.groupby(df["ticker"]).transform(
        lambda s: s.shift(N + 1).fillna(0).rolling(L, min_periods=1).max()
    ) > 0
    prior_power_black = power_black_today.groupby(df["ticker"]).transform(
        lambda s: s.shift(N + 1).fillna(0).rolling(L, min_periods=1).max()
    ) > 0

    is_red = df["close"] > df["open"]
    is_black = df["close"] < df["open"]
    bull_step = prior_power_red & narrow & is_red & (df["close"] > past_high_max)
    bear_step = prior_power_black & narrow & is_black & (df["close"] < past_low_min)

    return (bull_step | bear_step).fillna(False)
