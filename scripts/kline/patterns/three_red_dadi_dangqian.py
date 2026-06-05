"""大敵當前 — bear, exit (多單出場).

Course source: 第 06 篇《大敵當前》(AF12D42CF0CF4600F29D9C4ACA41C5B7)
Cross-course definition: PATTERN_INVENTORY P07.
Engineering proxy constants: THREE_RED_MAX_BODY_PCT, THREE_RED_MAX_HIGH_SPREAD.

注意：同時亦升級 exit/reversal_k/enemy_at_gate.py STUB 為更完整版本，
但保持兩處檔案獨立 (patterns/ = 純型態, exit/reversal_k/ = 沿用既有 mark API).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..course_proxy_constants import (
    THREE_RED_MAX_BODY_PCT,
    THREE_RED_MAX_HIGH_SPREAD,
)


def detect(df: pd.DataFrame) -> pd.Series:
    """大敵當前 — 長紅 K + 兩根拉不開紅 K + 跌破中值黑 K.

    Conditions (PATTERN_INVENTORY P07):
      1. D-3 為紅 K (長紅, 結構靠後續跌破中值認證, 不加 body 門檻 — PATTERN_DEFINITIONS §1)
      2. D-2, D-1 為紅 K, body_pct < THREE_RED_MAX_BODY_PCT (拉不開)
      3. D-2, D-1 之 high 與 D-3 之 high 距離 < THREE_RED_MAX_HIGH_SPREAD
      4. D-0 (今日) 黑 K, close < D-3 中值
    """
    g = df.groupby("ticker")
    open_d3 = g["open"].shift(3)
    close_d3 = g["close"].shift(3)
    high_d3 = g["high"].shift(3)
    open_d2 = g["open"].shift(2)
    close_d2 = g["close"].shift(2)
    high_d2 = g["high"].shift(2)
    open_d1 = g["open"].shift(1)
    close_d1 = g["close"].shift(1)
    high_d1 = g["high"].shift(1)

    d3_red = close_d3 > open_d3

    body_d2 = (close_d2 - open_d2).abs() / open_d2.replace(0, np.nan)
    body_d1 = (close_d1 - open_d1).abs() / open_d1.replace(0, np.nan)
    d2_red_small = (close_d2 > open_d2) & (body_d2 < THREE_RED_MAX_BODY_PCT)
    d1_red_small = (close_d1 > open_d1) & (body_d1 < THREE_RED_MAX_BODY_PCT)

    high_d3_safe = high_d3.replace(0, np.nan)
    d2_spread_ok = (high_d2 - high_d3) / high_d3_safe < THREE_RED_MAX_HIGH_SPREAD
    d1_spread_ok = (high_d1 - high_d3) / high_d3_safe < THREE_RED_MAX_HIGH_SPREAD

    d3_mid = (open_d3 + close_d3) / 2
    is_black = df["close"] < df["open"]
    breaks_mid = df["close"] < d3_mid

    return (
        d3_red & d2_red_small & d1_red_small & d2_spread_ok & d1_spread_ok
        & is_black & breaks_mid
    ).fillna(False)
