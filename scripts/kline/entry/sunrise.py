"""STUB: K線行進ing — 日出攻擊 (Sunrise attack).

Course source: K線行進ing 紅K篇(七) 日出攻擊.

Pending read of 行進ing subcategory. Replace this stub file
with the actual sunrise detection logic when ready.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
