"""鑷頂突破 + 攻擊確認 (strict variant).

Course source: 型態學 18-鑷頂 + 型態學 攻擊型態 four-pattern (combination).

This is a STRICTER variant of `tweezer_top_breakout` that ADDITIONALLY
requires the stock to already be in active attack mode (推升/跳空/日出)
on the entry day.

Trade-off vs. base tweezer:
  - Higher precision: filters out tweezer formations that don't immediately
    convert to attack (騙線型態 that appears to break but stalls).
  - Lower recall: may miss tweezer breakouts that ARE true attack starting
    points (intensity 0 → later attack begins after the breakout bar).
  - Use case: prioritise win rate over upside capture.

Course note: the course does NOT require attack mode for 鑷頂 entry.
This is a STRATEGY COMBINATION (鑷頂 + 攻擊型態 ranking), not a stricter
reading of the 鑷頂 chapter alone.

Required df columns: same as tweezer_top_breakout + attack_intensity.
"""
from __future__ import annotations

import pandas as pd

from .tweezer_top_breakout import detect as detect_base

MIN_ATTACK_INTENSITY = 2  # 推升攻擊 or stronger (推升=2, 跳空=3, 日出=4)


def detect(df: pd.DataFrame) -> pd.Series:
    """Returns bool Series. True = strict tweezer top breakout on that bar.

    Applies base tweezer_top_breakout (with clean_overhead) AND additionally
    requires attack_intensity >= MIN_ATTACK_INTENSITY on the entry bar.
    """
    base = detect_base(df)
    in_attack_mode = df["attack_intensity"].fillna(0) >= MIN_ATTACK_INTENSITY
    return (base & in_attack_mode).fillna(False)
