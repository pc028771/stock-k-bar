"""Shared helpers for 多空轉折組合 K 線 patterns.

PATTERN_DEFINITIONS.md reference:
  §1 力量型 K 線 (power_bar) — 雙軌設計，預設 NOT IMPLEMENTED；
  §2 多方力竭背景 (bull_exhaustion_context)；
  §3 空方力竭背景 (bear_exhaustion_context)。

Course sources:
  - docs/K線行進ing/01-關鍵K線的定義與使用目的.md:38
  - docs/K線行進ing/16-黑K篇二_高檔長黑.md:16-18
  - docs/型態學/07-反轉型態.md:19, 25, 51, 57
  - long_short_turning_point/B2E7A4597B7D1B50CF88163C892204D1_01-…:30
  - long_short_turning_point/E79401532D60CC63B302926C2C33FB50_02-…:22, 44, 118-122
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..course_proxy_constants import (
    BULL_EXHAUSTION_ATTACK_LOOKBACK,
    BULL_EXHAUSTION_NEAR_HIGH_PCT,
)


def is_power_bar(df: pd.DataFrame, direction: str = "bull") -> pd.Series:
    """力量型 K 線 — 雙軌設計，預設 NOT IMPLEMENTED.

    PATTERN_DEFINITIONS §1 結論：課程內部矛盾 — 「形狀不重要」(行進ing
    01:38 / 認知篇) vs 具體型態定義字面「長黑」「長紅」。

    建議：detect() 預設不加 body 門檻，靠結構動作（摜破、跌破中值、實體
    包覆）保證 K 棒夠強。本 helper 保留 Option B 雙軌設計但預設 raise，
    避免被誤用。

    Option B (commented OFF) 數字：
        body_pct ≥ percentile_70(body_pct, 20d) AND body_pct ≥ 1.5%

    Refs:
      - PATTERN_DEFINITIONS.md §1 (lines 15-94)
      - docs/K線行進ing/01-關鍵K線的定義與使用目的.md:38
        「關鍵K線的形狀並不重要——並非長紅或長黑才算得上關鍵K線。」
    """
    raise NotImplementedError(
        "is_power_bar() is intentionally not implemented — PATTERN_DEFINITIONS §1 "
        "結論建議靠結構動作判定力量，不靠 body 門檻。Option B 雙軌見 docstring。"
    )
    # --- Option B (kept commented for future audit) ---
    # if "body_pct_pct_rank_20d" not in df.columns:
    #     raise KeyError("body_pct_pct_rank_20d feature missing")
    # color = df["is_red"] if direction == "bull" else df["is_black"]
    # return color.fillna(False) & (df["body_pct_pct_rank_20d"] >= 0.7) & (df["body_pct"] >= 0.015)


def bull_exhaustion_context(df: pd.DataFrame) -> pd.Series:
    """多方力竭背景 — PATTERN_DEFINITIONS §2 規格.

    課程明示「高檔沒辦法用數字定義」(行進ing 16:16-18). 代理三條件 AND:
      1. attack_intensity ≥ 1 (過去 5 日內處於攻擊狀態)
      2. 過去 60 日內曾經 close > prior_high_60 (拉抬發生過)
      3. 今日 close ≥ prior_high_60 × 0.95 (沒跌離高檔)

    Refs:
      - PATTERN_DEFINITIONS.md §2 (lines 96-165)
      - docs/型態學/07-反轉型態.md:19
      - long_short_turning_point/E79401532D60CC63B302926C2C33FB50_02-…:22

    Required df columns: attack_intensity, close, prior_high_60, ticker.
    """
    g_attack = (
        df["attack_intensity"]
        .groupby(df["ticker"])
        .rolling(BULL_EXHAUSTION_ATTACK_LOOKBACK, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
    )
    in_attack_recent = g_attack >= 1

    breakout_indicator = (df["close"] > df["prior_high_60"]).fillna(False).astype(int)
    was_breakout_60d = (
        breakout_indicator
        .groupby(df["ticker"])
        .rolling(60, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
        > 0
    )

    near_high = df["close"] >= df["prior_high_60"] * BULL_EXHAUSTION_NEAR_HIGH_PCT

    return (in_attack_recent & was_breakout_60d & near_high).fillna(False)


def bear_exhaustion_context(df: pd.DataFrame) -> pd.Series:
    """空方力竭背景 — PATTERN_DEFINITIONS §3 規格.

    課程明示比多方力竭更嚴格 (型態學 07:51 「再加邏輯」). 代理兩條件 AND:
      1. is_in_breakdown_pattern (features.py 既有 — 破底型態)
      2. (可選) supply_vacuum_zone — features.py 未實作則 fallback 為 True

    NOTE: PATTERN_DEFINITIONS §3 指出「大盤悲觀」filter 課程明示需要，
    但屬跨股 query，留給上層 simulator 套用，本層不做。

    Refs:
      - PATTERN_DEFINITIONS.md §3 (lines 167-219)
      - docs/型態學/07-反轉型態.md:25, 57
      - long_short_turning_point/E79401532D60CC63B302926C2C33FB50_02-…:118-122

    Required df columns: is_in_breakdown_pattern, ticker.
    """
    in_breakdown = df["is_in_breakdown_pattern"].fillna(False)
    if "supply_vacuum_zone" in df.columns:
        has_supply_vacuum = df["supply_vacuum_zone"].fillna(False)
        return (in_breakdown & has_supply_vacuum).astype(bool)
    return in_breakdown.astype(bool)
