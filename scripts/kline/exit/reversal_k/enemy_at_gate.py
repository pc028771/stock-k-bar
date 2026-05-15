"""STUB: 多空轉折組合K線 — 大敵當前 (Enemy at gate).

Course source: 多空轉折組合K線 — 三根K線連續判斷阻礙力量出現：大敵當前.

Intro course only mentions by name + 藍天 example. Detailed structural
definition is in the 多空轉折 subcategory. Replace this stub when read.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
