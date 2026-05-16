"""Strict pattern breakout entry — only operation starting points.

Course source: 型態學 03-箱型整理 + 05-三角收斂 + 14-推升攻擊 + K線行進ing 事件十.

> 「型態突破 = 突破新高價的當天，前面有 2.5–3 個月的整理區間」
> 「不到 3 個月但有低點推升 → 中繼 (continuation), NOT 起點」
> 「起點是一定要參與的, 等到了中繼的再突破已經慢了」

Pattern detection is course-faithful (NOT a range-proxy):
  - 低點漸漸墊高 (rising lows): >= 30 of 60 prior days had higher_low
  - 上緣穩定 (stable ceiling): prior_high_60 vs prior_high_30 spread <= 5%
  - 突破上緣: close > prior_high_60
  - 站上 MA60

This excludes "sleeping" flat-range stocks (no rising lows = no 主力收貨 signal).

This is a STRICTER alternative to `breakout_attack`:
- `breakout_attack` admits both starting points AND continuations
- `pattern_breakout_only` admits ONLY starting points

Also excludes 破底型態 stocks (型態學 16).

Required df columns: is_pattern_breakout, is_in_breakdown_pattern.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = strict pattern breakout entry."""
    is_pb = df["is_pattern_breakout"].fillna(False)
    not_breakdown = ~df["is_in_breakdown_pattern"].fillna(False)
    return (is_pb & not_breakdown).fillna(False)
