"""STUB: K線行進ing — Position-based shadow scoring.

Course source: K線行進ing 影線篇(一)(二) — 上影線在不同位置的意義.

> 「同樣的上影線在新高、遇壓、整理三種位置意義完全不同」

Replace this stub when 行進ing subcategory is read.
"""
from __future__ import annotations

import pandas as pd


def score(df: pd.DataFrame) -> pd.Series:
    return pd.Series(0.0, index=df.index)
