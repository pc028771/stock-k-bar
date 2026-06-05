"""中性包覆 (無力竭背景的吞噬) — context_only.

Course source: 第 18 篇《包覆型態》(2BA211D9CB1514E34D087249F9D627B7)
Cross-course definition: PATTERN_INVENTORY P19.
Engineering proxy constants: REBOUND_VOLUME_RATIO_MIN.
"""
from __future__ import annotations

import pandas as pd

from ..course_proxy_constants import REBOUND_VOLUME_RATIO_MIN


def detect(df: pd.DataFrame) -> pd.Series:
    """中性包覆 — 不論方向，今日實體包覆前日 + 有量加強.

    Conditions (PATTERN_INVENTORY P19):
      1. 實體包覆 (max(open, close) >= prev_high AND min(open, close) <= prev_low)
         — 採課程「弱包覆」放寬版：高低點包覆
      2. 顏色相反 (前日紅今日黑 OR 前日黑今日紅)
      3. 有量 (volume_ratio >= 1.5)

    與 P02/P03 區別：本 detect **不要求力竭背景**，故 context_only.
    """
    g = df.groupby("ticker")
    prev_open = g["open"].shift(1)
    prev_close = g["close"].shift(1)
    prev_high_v = g["high"].shift(1)
    prev_low_v = g["low"].shift(1)

    body_engulf = (
        (df[["open", "close"]].max(axis=1) >= prev_high_v)
        & (df[["open", "close"]].min(axis=1) <= prev_low_v)
    )

    prev_red = prev_close > prev_open
    prev_black = prev_close < prev_open
    today_red = df["close"] > df["open"]
    today_black = df["close"] < df["open"]
    opposite = (prev_red & today_black) | (prev_black & today_red)

    has_volume = df["volume_ratio"].fillna(0) >= REBOUND_VOLUME_RATIO_MIN

    return (body_engulf & opposite & has_volume).fillna(False)
