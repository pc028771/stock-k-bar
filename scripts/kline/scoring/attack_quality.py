"""Attack quality score.

Course source: Calibrated via Spearman correlation against trade_return_net
              over course-defined exit simulation (n≈6,618). Factors map to
              attack-authenticity course concepts:
                - pre_breakout_trend_days: trend-following 真攻擊
                - volume_ratio: extreme volume often = retail FOMO peak
                - body_pct: oversized red K often = exhaustion
                - close_pos: pinned-to-high often = unable to absorb selling

Base 50 + factor deltas, clipped to [0, 100].
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series in [0, 100]. Higher = better attack quality.

    Required df columns: pre_breakout_trend_days, volume_ratio, body_pct, close_pos.
    """
    s = pd.Series(50.0, index=df.index)
    s += np.where(df["pre_breakout_trend_days"].fillna(0) >= 17, 25, 0)
    s -= np.where(df["volume_ratio"].fillna(0) >= 3.2, 30, 0)
    s -= np.where(df["body_pct"].fillna(0) >= 0.04, 25, 0)
    s -= np.where(df["close_pos"].fillna(0) >= 0.85, 20, 0)
    return s.clip(0, 100)
