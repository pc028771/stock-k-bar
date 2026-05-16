"""Attack intensity score — ranks candidates by attack pattern strength.

Course source: 型態學 攻擊型態 four-pattern ranking.

Score:
  +20 if attack_intensity == 4 (日出攻擊)
  +15 if attack_intensity == 3 (跳空攻擊)
  +10 if attack_intensity == 2 (推升攻擊)
  +5  if attack_intensity == 1 (波動前進)
  0   if attack_intensity == 0 (no attack)

Required df columns: attack_intensity.
"""
from __future__ import annotations

import pandas as pd

SCORE_MAP = {0: 0.0, 1: 5.0, 2: 10.0, 3: 15.0, 4: 20.0}


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series. Bonus for stronger attack patterns."""
    intensity = df["attack_intensity"].fillna(0).astype(int)
    return intensity.map(SCORE_MAP).astype(float)
