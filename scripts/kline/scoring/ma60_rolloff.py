"""MA60 carry-off (扣抵) pressure score.

Course source: 【移動平均】季線與K線高低點.

MA60 direction tomorrow is determined by comparing today's new close
against the close from 60 bars ago (which is about to roll off the window).

  new_close > rolling_off_close → MA60 turns up tomorrow  (bullish)
  new_close < rolling_off_close → MA60 turns down tomorrow (bearish)

This factor adds a small bonus/penalty proportional to the carry-off
direction.

Required df columns: close, ma60_rolling_off_close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MAX_DELTA = 10.0  # cap so extreme rolloffs don't dominate


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series.

      +10 if rolling_off_close is well below current close
      −10 if well above
      0 otherwise / NaN
    """
    delta = df["close"] - df["ma60_rolling_off_close"]
    norm = (delta / df["close"].replace(0, np.nan)).clip(-0.10, 0.10) / 0.10
    return (norm * MAX_DELTA).fillna(0.0)
