"""STUB: 多空轉折組合K線 — 夜星棄嬰 (Abandoned evening star).

Course source: 多空轉折組合K線 — 三根K線連續判斷在十字線之後：夜星棄嬰.

No structural definition in the intro course. Replace this stub when
多空轉折 subcategory is read.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
