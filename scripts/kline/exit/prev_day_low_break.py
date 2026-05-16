"""Previous-day low break exit signal — short-term trading.

Course source: 【買點賣點】買點與攻擊研判 + 紅K篇(二).

> 「短線操作的停利點可以設定在昨天的低點」

Course-required gate (紅K篇(二) / 買點與攻擊研判):
  The previous bar must have **攻擊意義** for "跌破前一日低點" to count as
  an attack stop. Without that gate the rule degenerates into a pure
  mechanical stop on any prior low — which the course does NOT teach.

  攻擊意義 = previous bar was one of:
    (a) red K creating a new 60-day high, OR
    (b) upper-shadow K at a new high, OR
    (c) doji follow-up after a red attack K.

The `prev_bar_had_attack_meaning` flag is computed in `features.add_features()`.

Required df columns: close, prev_low, prev_bar_had_attack_meaning.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = close < prev_low AND previous bar had 攻擊意義."""
    broke = df["close"] < df["prev_low"]
    if "prev_bar_had_attack_meaning" not in df.columns:
        # Conservative: without the gate column, do not fire — keeps the
        # course-required attack-context restriction.
        return pd.Series(False, index=df.index)
    gate = df["prev_bar_had_attack_meaning"].fillna(False).astype(bool)
    return (broke & gate).fillna(False)
