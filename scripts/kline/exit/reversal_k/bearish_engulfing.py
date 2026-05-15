"""STUB: 多空轉折組合K線 — 空頭吞噬 (Bearish engulfing).

Course source: 多空轉折組合K線 — 包覆線在轉折組合中的運用 (multi-side bear-side).

Intro course mentions by name only. Structural definition is in the
多空轉折組合K線 subcategory (26 articles). Replace this stub when read.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
