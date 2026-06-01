"""高檔吊首 — bear, exit (多單出場).

Course source: 第 04 篇《高檔下影線：高檔吊首》(666C90D7BC58F0E0E9629CAD711FD56F)
Cross-course definition: PATTERN_DEFINITIONS.md §2 + PATTERN_INVENTORY P05.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._common import bull_exhaustion_context


def detect(df: pd.DataFrame) -> pd.Series:
    """高檔吊首 — T 字線 (長下影線) + 多方力竭 + 確認日 (日落 OR 開低跳空).

    Conditions (PATTERN_INVENTORY P05):
      1. 多方力竭背景
      2. 前一日為 T 字 / 近 T 字 (下影 >= 2x body, 上影 <= 0.3x body)
      3. 確認：今日為日落 (is_sunset_bar) OR 今日 open < prev_low
      4. 排除：日出攻擊進行中 (attack_intensity == 4)
    """
    g = df.groupby("ticker")
    prev_lower = g["lower_shadow"].shift(1)
    prev_upper = g["upper_shadow"].shift(1)
    prev_body = g["body_abs"].shift(1).replace(0, np.nan)
    prev_low_v = g["low"].shift(1)

    t_line = (prev_lower >= 2 * prev_body) & (prev_upper <= 0.3 * prev_body)

    confirm = df["is_sunset_bar"].fillna(False) | (df["open"] < prev_low_v)

    not_sunrise_attack = df["attack_intensity"].fillna(0) != 4

    exhaust = bull_exhaustion_context(df)

    return (t_line & confirm & not_sunrise_attack & exhaust).fillna(False)
