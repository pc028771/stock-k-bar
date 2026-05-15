"""STUB: 多空轉折組合K線 — 雙鴉躍空 (Two crows).

Course source: 多空轉折組合K線 — 向下跳空形成的壓力：雙鴉躍空.

Intro course gives partial hint ("紅K後接續兩根短黑K，然後再出現一個向下跳空");
precise structural definition is in 多空轉折 subcategory. Replace when read.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
