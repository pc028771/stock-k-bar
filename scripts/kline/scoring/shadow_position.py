"""Position-based shadow scoring.

Course source: K線行進ing 上影線(一) 出現位置與定義的關聯
              + K線行進ing 上影線(二) 不同位置的上影線
              + K線行進ing 下影線與人們的想像不同

Key rules:
  - Upper shadow at new high (and red K) = attack signal (POSITIVE)
  - Upper shadow at overhead supply zone (not new high) = pressure (NEGATIVE)
  - Lower shadow: completely ignored (course explicitly says no support meaning)

Required df columns: high, prior_high_60, upper_shadow_ratio,
                      overhead_supply_layer, is_red.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ATTACK_BONUS = 10
PRESSURE_PENALTY = 10
SHADOW_MIN_RATIO = 1.0  # upper shadow >= 1x body to count


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series.

      +10 if upper shadow at new high with red K (attack signal)
      -10 if upper shadow at overhead supply zone but NOT new high (pressure)
       0 otherwise
    """
    is_new_high = df["high"] > df["prior_high_60"]
    has_upper_shadow = df["upper_shadow_ratio"].fillna(0) >= SHADOW_MIN_RATIO
    is_at_overhead = df["overhead_supply_layer"].fillna(0) >= 1
    is_red = df["is_red"]

    is_attack_shadow = is_new_high & has_upper_shadow & is_red
    is_pressure_shadow = is_at_overhead & has_upper_shadow & ~is_new_high

    s = pd.Series(0.0, index=df.index)
    s += np.where(is_attack_shadow, ATTACK_BONUS, 0)
    s -= np.where(is_pressure_shadow, PRESSURE_PENALTY, 0)
    return s
