"""Strict pattern breakout entry — only operation starting points.

Course source: 型態學 03-箱型整理 + K線行進ing 事件十 操作的開始與結束.

> 「型態突破 = 突破新高價的當天，前面有 2.5–3 個月的整理區間」
> 「不到 3 個月但有低點推升 → 中繼 (continuation), NOT 起點」
> 「起點是一定要參與的, 等到了中繼的再突破已經慢了」

This is a STRICTER alternative to `breakout_attack`:
- `breakout_attack` admits both starting points AND continuations
- `pattern_breakout_only` admits ONLY starting points

Use this entry signal for trading systems that want to:
- Reduce false signals (continuation entries are weaker)
- Focus on operation starting points (主力剛開始拉抬)
- Trade fewer but higher-quality setups

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
