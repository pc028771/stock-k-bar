"""Trend-continuation bonus — course-faithful pre-breakout trend strength.

Course source: 入門 / 行進ing 順勢交易 + 季線多頭背景.

> 「攻擊發動前若已長期站穩季線，順勢交易的勝率較高。」

This factor rewards candidates whose pre-breakout history shows sustained
above-MA60 closes — a trend-following bias the course endorses.

## Origin (audit C4 / attack_quality split — option B)

Previously, the legacy `attack_quality` scoring factor combined a
course-aligned positive contribution (`pre_breakout_trend_days ≥ N → +25`)
with three anti-course penalties (volume_ratio, body_pct, close_pos). The
penalties violated course's "do not use volume / body / close_pos as
entry filters" rule and were moved to
`extras.attack_quality_anti_course_penalties` (default OFF).

This factor is the surviving course-aligned half. It is registered in the
default scanner SCORING_REGISTRY.

## Proxy

The threshold N = 17 (days above MA60 in past 20) was originally chosen
by Spearman-correlation inflection in backtest. Course gives no number,
so we keep it as a proxy. See `course_proxy_constants.TREND_CONTINUATION_MIN_DAYS`.

Score:
  +25 if pre_breakout_trend_days >= TREND_CONTINUATION_MIN_DAYS (default 17)
   0  otherwise

Required df columns: pre_breakout_trend_days.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..course_proxy_constants import (
    TREND_CONTINUATION_BONUS,
    TREND_CONTINUATION_MIN_DAYS,
)


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series. 0 or +TREND_CONTINUATION_BONUS."""
    return pd.Series(
        np.where(
            df["pre_breakout_trend_days"].fillna(0) >= TREND_CONTINUATION_MIN_DAYS,
            TREND_CONTINUATION_BONUS,
            0.0,
        ),
        index=df.index,
        dtype=float,
    )
