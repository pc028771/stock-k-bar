"""Attack intensity score — ranks candidates by attack pattern strength.

Course source: 型態學 攻擊型態 four-pattern ranking.

Proxy disclosure (I1): the four-level ranking comes from course directly.
The COUNTING THRESHOLDS that drive the levels (≥ 4 of 5 higher-low for
推升, ≥ 4 of 5 higher-high for 波動) are operationalizations of qualitative
course descriptions, not course-stated numbers. See
`course_proxy_constants.py` (ATTACK_HIGHER_LOW_MIN_5DAY etc.) and the
relevant feature-pipeline code in `features.py`.

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
