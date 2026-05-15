"""STUB: K線行進ing — 精確頸線 via 關鍵K線 × MA60.

Course source: K線行進ing 關鍵K線延伸篇 — 關鍵K線與移動平均線的連結判斷.

Replaces the prior_low_20 proxy used in neckline_break.py with a course-
precise neckline: "prior high after MA60 turns up" / "prior low after MA60
turns down". Pending read of 行進ing subcategory.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
