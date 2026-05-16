"""Pattern breakout bonus — course-faithful starting-point detection.

Course source:
  - 型態學 05-三角收斂 (低點墊高 + 上緣穩定 = 主力收貨三角收斂)
  - 型態學 08-騙線型態 (上有壓力的突破 = 最常見的陷阱 → 須先化解套牢)
  - 型態學 14-推升攻擊 (低點推升型態 = 不給散戶低接機會)
  - 型態學 03-箱型整理 + K線行進ing 事件十 (起點 vs 中繼)
  - 行進ing 24-跳空篇三 (攻擊跳空精確邊界 = 過去沒有成交過的價位)
  - 入門 賣壓化解 (等越過了之後才能確定有攻擊意願)

A "true" pattern breakout is defined course-directly as (5 conditions, ALL AND):
  A. 低點漸漸墊高 (rising lows, >= 30 of 60 days)
  B. 上緣穩定 (stable upper boundary / ceiling, spread <= 5%)
  C. 上方無套牢 (clean overhead: overhead_supply_layer == 0 AND
       unfilled_gap_down_count_240d == 0; covers both 套牢型 and 型態型 overhead)
  D. 突破上緣 (close > prior 60-day high)
  E. 站上 MA60 (multi background confirmation)

This distinguishes true 主力收貨三角收斂 from:
  - "sleeping" flat stocks (no rising lows — NOT course pattern)
  - 騙線型態 (breakout into overhead supply — most common trap per course)

Score:
  +20 if is_pattern_breakout = True
  0 otherwise

Magnitude rationale: 起點 must participate per course ("起點是一定要參與的"),
so a strong bonus (10% of the 200-point clip cap) is justified.

Required df columns: is_pattern_breakout.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PATTERN_BREAKOUT_BONUS = 20


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series. +20 for pattern breakout, else 0."""
    is_pb = df["is_pattern_breakout"].fillna(False)
    return pd.Series(np.where(is_pb, PATTERN_BREAKOUT_BONUS, 0.0), index=df.index)
