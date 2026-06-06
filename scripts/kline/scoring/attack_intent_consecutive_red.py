"""攻擊意圖闕如：連續紅K 但無 gap-up — scoring negative factor.

Course source: K線力量入門「紅色誤解」+ §31 攻擊延續性研判
  入門「紅色誤解」chapter: 「攻擊的理論基礎就是剛剛開始就不會回頭、不可能給人
   又有太多機會低檔買進」
  入門 §31: 「突破之後遇到突破的隔天就開平或下跌、顯然不具備攻擊意願」

Concept:
  突破日後若連續紅K但每根都是低開或開平（無 gap-up），代表多方力量不足以
  「不給人低檔買進」 → 攻擊意圖闕如。此為負分 scoring component。

Scoring logic (退化版日 K):
  - 找到突破日 (is_first_breakout_above_level=True)
  - 突破日後 ATTACK_INTENT_WINDOW_DAYS 內，計算「紅 K 但 open <= prev_close」天數
  - 若 ≥ ATTACK_INTENT_RED_NO_GAP_MIN，每多 1 天扣 ATTACK_INTENT_PENALTY_PER_DAY 分，
    上限 ATTACK_INTENT_MAX_PENALTY

Required df columns:
  ticker, open, close, prev_close, is_red, is_first_breakout_above_level.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..course_proxy_constants import (
    ATTACK_INTENT_WINDOW_DAYS,
    ATTACK_INTENT_RED_NO_GAP_MIN,
    ATTACK_INTENT_PENALTY_PER_DAY,
    ATTACK_INTENT_MAX_PENALTY,
)


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series in range [ATTACK_INTENT_MAX_PENALTY, 0].

    For each bar, look backward ATTACK_INTENT_WINDOW_DAYS for a breakout day.
    If found, count subsequent "red K without gap-up" bars in the window.
    If count >= ATTACK_INTENT_RED_NO_GAP_MIN, apply -1 per day, capped.

    All components are non-positive (闕如 = 負分).
    """
    g = df.groupby("ticker")

    # "No gap-up red K": is_red AND open <= prev_close (低開或開平)
    is_red = df.get("is_red")
    if is_red is None:
        is_red = (df["close"] > df["open"])
    is_red = is_red.fillna(False)
    no_gap_up = (df["open"] <= df["prev_close"]).fillna(False)
    no_intent_bar = (is_red & no_gap_up).astype(int)

    # Was there a breakout within the past ATTACK_INTENT_WINDOW_DAYS days?
    breakout = df.get("is_first_breakout_above_level")
    if breakout is None:
        # Fall back: today's close > prior_high_60 (any breakout, conservative)
        breakout = (df["close"] > df.get("prior_high_60", df["close"])).fillna(False)
    breakout_int = breakout.fillna(False).astype(int)

    # Rolling sum: any breakout in past N days (exclude today via shift(1))
    had_recent_breakout = (
        g.apply(lambda x: x.set_index(np.arange(len(x))))  # noop chain
    )  # placeholder
    # Simpler: rolling sum on shifted series
    breakout_window = (
        breakout_int.groupby(df["ticker"]).transform(
            lambda s: s.shift(1).rolling(ATTACK_INTENT_WINDOW_DAYS, min_periods=1).sum()
        )
        .fillna(0)
    )
    in_post_breakout = breakout_window > 0

    # Count no-intent bars in the same window (including today)
    no_intent_window = (
        no_intent_bar.groupby(df["ticker"]).transform(
            lambda s: s.rolling(ATTACK_INTENT_WINDOW_DAYS, min_periods=1).sum()
        )
        .fillna(0)
    )

    # Apply penalty when count >= MIN and we're in post-breakout window
    triggered = in_post_breakout & (no_intent_window >= ATTACK_INTENT_RED_NO_GAP_MIN)
    penalty = (no_intent_window * ATTACK_INTENT_PENALTY_PER_DAY).clip(
        lower=ATTACK_INTENT_MAX_PENALTY, upper=0.0
    )
    s = pd.Series(0.0, index=df.index)
    s = s.where(~triggered, penalty)
    return s.fillna(0.0)
