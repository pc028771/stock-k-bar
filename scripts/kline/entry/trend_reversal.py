"""STUB: 入門 — 底部轉折型買點 (Buy at trend change, post-bear).

Course source: 【買點賣點】出場點(一) — three entry types include trend-change buy.

Intro course mentions this entry type but does not give precise structural
detection (requires MA60 turning up from down, plus bottom-pattern completion).

Replace this stub when precise detection is finalized.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    return pd.Series(False, index=df.index, dtype=bool)
