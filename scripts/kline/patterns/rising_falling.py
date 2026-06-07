"""升降組合型態 — 上升一階 / 下降一階, context_only.

Course source: 第 25 篇《升降組合型態》(0B1DD310D7685EE74123E5147BB7CFB2)
Cross-course definition: PATTERN_INVENTORY P26.
Engineering proxy constants: NARROW_CONSOLIDATION_BARS, NARROW_CONSOLIDATION_RANGE_MAX.

與咬定型態 (P25) 的差異：升降「之前先有一根原本方向的力量 K」.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import NARROW_CONSOLIDATION_BARS
from ._common import is_narrow_consolidation, is_power_bar, is_single_ticker

PRIOR_POWER_LOOKBACK = 20  # course-not-stated — proxy 一個月內


def detect(df: pd.DataFrame) -> pd.Series:
    """上升一階 OR 下降一階任一觸發.

    Conditions (PATTERN_INVENTORY P26, refactored to use _common helpers):
      上升一階:
        1. 過去 PRIOR_POWER_LOOKBACK 天內出現過力量型紅 K (is_power_bar bull)
        2. 接著有 N 天狹幅整理 (is_narrow_consolidation, close-level)
        3. 今日再出現紅 K 突破整理區 close 最大值

      下降一階: 反相.
    """
    N = NARROW_CONSOLIDATION_BARS
    consol = is_narrow_consolidation(df, use_close=True)
    narrow = consol["narrow"]
    past_close_max = consol["past_close_max"]
    past_close_min = consol["past_close_min"]

    # 過去 PRIOR_POWER_LOOKBACK 天內出現過力量型 K — body_pct ≥ 3% (default)
    power_red_today = is_power_bar(df, "bull").astype(int)
    power_black_today = is_power_bar(df, "bear").astype(int)
    L = PRIOR_POWER_LOOKBACK

    if is_single_ticker(df):
        # Fast path — skip groupby+lambda overhead (~10× faster on a 1000-row df).
        prior_power_red = (
            power_red_today.shift(N + 1).fillna(0).rolling(L, min_periods=1).max() > 0
        )
        prior_power_black = (
            power_black_today.shift(N + 1).fillna(0).rolling(L, min_periods=1).max() > 0
        )
    else:
        prior_power_red = power_red_today.groupby(df["ticker"]).transform(
            lambda s: s.shift(N + 1).fillna(0).rolling(L, min_periods=1).max()
        ) > 0
        prior_power_black = power_black_today.groupby(df["ticker"]).transform(
            lambda s: s.shift(N + 1).fillna(0).rolling(L, min_periods=1).max()
        ) > 0

    bull_step = prior_power_red & narrow & is_power_bar(df, "bull") & (df["close"] > past_close_max)
    bear_step = prior_power_black & narrow & is_power_bar(df, "bear") & (df["close"] < past_close_min)

    return (bull_step | bear_step).fillna(False)
