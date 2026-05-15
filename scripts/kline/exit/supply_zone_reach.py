"""STUB: 入門 — 遇壓先出，化解再進 (Supply zone reach).

Course source: 【買點賣點】出場點的各種依據-下一個買點.

> 「應該先出場，等到股價越過了這個壓力區段，再考慮還有沒有買回的意義」

Requires volume profile (分價量表) for precise resistance identification.
Pending VP integration. Replace this stub when VP module is ready.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
