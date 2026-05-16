"""Pattern breakout bonus — course-aligned starting-point detection.

Course source:
  - 型態學 03-箱型整理 (3-month box + breakout = pattern breakout)
  - K線行進ing 事件十 (operation starting point vs continuation)

A "true" pattern breakout (with prior 3-month box integration) is the
operation starting point per course. Without prior integration, the breakout
is merely a continuation/mid-attack signal.

Score:
  +20 if is_pattern_breakout = True
  0 otherwise

Magnitude rationale: 起點 must participate per course ("起點是一定要參與的"),
so a strong bonus (10% of the 200-point clip cap) is justified.

Implementation caveat: the underlying `is_in_60day_box` uses a 15% range
proxy that is NOT course-stated. The course describes box shape qualitatively;
the 15% threshold is a pragmatic implementation choice (see features.py).

Required df columns: is_pattern_breakout.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PATTERN_BREAKOUT_BONUS = 20


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series. +20 for pattern breakout, else 0."""
    is_pb = df["is_pattern_breakout"].fillna(False)
    return pd.Series(np.where(is_pb, PATTERN_BREAKOUT_BONUS, 0.0), index=df.index)
