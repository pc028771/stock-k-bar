"""STUB: 多空轉折組合K線 — 跳空反轉 (Gap reversal).

Course source: 多空轉折組合K線 — 向下跳空出現的影響：跳空反轉與延伸解說.

Intro course gives partial hint ("紅K後接黑K再向下跳空"); precise definition
is in 多空轉折 subcategory. Replace when read.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
