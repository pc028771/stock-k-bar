"""咬定型態 — context_only / entry-support (多方咬定可作主力大「整理完突破」訊號).

Course source: 第 24 篇《咬定型態》(A5C5E3F242DCE38F0E9061E3FBC85B81)
Cross-course definition: PATTERN_INVENTORY P25.
Engineering proxy constants: via _common helpers.
"""
from __future__ import annotations

import pandas as pd

from ._common import is_narrow_consolidation, is_power_bar


def detect(df: pd.DataFrame) -> pd.Series:
    """多方咬定 OR 空方咬定 — 狹幅整理後力量型 K 突破/跌破.

    Conditions (PATTERN_INVENTORY P25, refactored to use _common helpers):
      多方咬定:
        1. 過去 N 根狹幅整理 (is_narrow_consolidation, close-level range)
        2. 今日紅 K + 力量型 (is_power_bar bull body ≥ 3%)
        3. close > 過去 close 最高 (close-level breakout)

      空方咬定: 反相 — 今日黑 K + close < 過去 close 最低.

    Case calibration:
      - Case #5 奇鋐 3017 2022-02-17: body +7.1% ✓ red, breaks past close max
      - Case #6 富邦媒 8454 2022-02-25: body -3.6% ✓ black, breaks past close min
    """
    consol = is_narrow_consolidation(df, use_close=True)
    narrow = consol["narrow"]
    past_close_max = consol["past_close_max"]
    past_close_min = consol["past_close_min"]

    bull_power = is_power_bar(df, direction="bull")
    bear_power = is_power_bar(df, direction="bear")

    bull_bite = narrow & bull_power & (df["close"] > past_close_max)
    bear_bite = narrow & bear_power & (df["close"] < past_close_min)

    return (bull_bite | bear_bite).fillna(False)
