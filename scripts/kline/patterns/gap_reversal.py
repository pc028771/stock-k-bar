"""跳空反轉 — bear, exit.

Course source: 第 08 篇《跳空反轉》(92E64EAB9982ADE91CB903046E5FA04F)
Cross-course definition: PATTERN_INVENTORY P09.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """跳空反轉 — 攻擊 / 表面強勢後出現向下跳空 + 無力回補.

    Conditions (PATTERN_INVENTORY P09, adjusted 2026-06-03 per Case #13):
      1. 過去 30 日內有攻擊狀態 (recent_attack — 寬鬆 context)
         Course line 34 明示「跳空反轉不一定只出現在創新高的位置，往往有著
         『表面上看起來強勢』的非創新高時期，也很常出現」— 不能限制
         「今日 close 近高」。
      2. 今日 open < prev_low (向下跳空 — 真實 K-bar gap)
      3. 今日 close < prev_low (收盤無力回補)

    Case #13 calibration:
      - 4908 前鼎 2019-12-11: D-2 大紅 +7%, D-1 黑K, D-0 gap down -6.5% ✓
      - 4908 前鼎 2020-07-28: 已從 50 跌到 38，但 7 月初有攻擊 (07-23 +7.5%
        創新高)，符合「表面上強勢後跳空」context — 不該被「今日 close 近高」
        過濾掉
    """
    g = df.groupby("ticker")
    prev_low_v = g["low"].shift(1)
    gap_down_open = df["open"] < prev_low_v
    no_fill_close = df["close"] < prev_low_v

    # 過去 30 日內有攻擊狀態 (attack_intensity ≥ 1 within past 30 days).
    # 比 bull_exhaustion_context (要求今日仍近高) 寬鬆，符合 course line 34.
    in_recent_attack = (
        df["attack_intensity"]
        .groupby(df["ticker"])
        .rolling(30, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
        >= 1
    )

    return (gap_down_open & no_fill_close & in_recent_attack).fillna(False)
