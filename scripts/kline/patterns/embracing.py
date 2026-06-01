"""懷抱型態 — 無力竭背景的孕線, context_only.

Course source: 第 20 篇《懷抱型態》(161D653D96BB64939DE424B8B5162815)
Cross-course definition: PATTERN_INVENTORY P21.
"""
from __future__ import annotations

import pandas as pd


def detect(df: pd.DataFrame) -> pd.Series:
    """懷抱型態 — 前日為力量型 K + 今日醞釀型短 K (孕線).

    Conditions (PATTERN_INVENTORY P21):
      1. 前一日為力量型 K — 課程「形狀不重要」原則下，採「前日 body_pct
         相對較大」作結構代理 (prev body_abs > today body_abs × 2)
      2. 今日為孕線 (is_harami)
      3. 今日醞釀短 K — body_pct < 1% OR is_doji
      4. 紅黑顏色組合不限
    """
    g = df.groupby("ticker")
    prev_body = g["body_abs"].shift(1)
    today_body_v = df["body_abs"]

    prev_was_power = prev_body > today_body_v * 2

    today_harami = df["is_harami"].fillna(False)
    today_short = df["is_doji"].fillna(False) | (df["body_pct"].fillna(1.0) < 0.01)

    return (prev_was_power & today_harami & today_short).fillna(False)
