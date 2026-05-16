"""EXTRA: Anti-course penalties from the legacy attack_quality factor.

**本檔案內容非課程定義** — 三個 entry-side 罰分項目（volume_ratio、body_pct、
close_pos）保留在 extras 供 backtest 對照、研究用。Default OFF；透過
`--extras attack_quality_anti_course_penalties` 啟用。

## Origin (audit C4 → split into two halves — option B)

Original `scripts/kline/scoring/attack_quality.py` had four sub-factors:
  1. `pre_breakout_trend_days >= 17 → +25` (course-aligned: 順勢交易).
  2. `volume_ratio >= 3.2  → -30`         (anti-course: 課程明文反對 volume 過濾).
  3. `body_pct >= 0.04     → -25`         (anti-course: 課程明文反對 body 過濾).
  4. `close_pos >= 0.85    → -20`         (anti-course: 課程明文反對 close_pos 過濾).

The +25 trend_days contribution was promoted to
`scripts/kline/scoring/trend_continuation.py` (default ON in
SCORING_REGISTRY). This module retains ONLY the three anti-course
penalties.

## Why the penalties are anti-course

課程（突破跌破 — 突破意義的釐清）明文表示：
> 「對於K線圖來說，價格才是最重要的事情，不需要加上成交量」
> 「與這一根突破的K線是否長紅、有沒有上影線都無關」

亦違反 CLAUDE.md「禁止將回測分析結論套用在個股操作建議上」。

## 校準來源

Thresholds (3.2, 0.04, 0.85) picked by Spearman-correlation inflection
points in backtest (n≈6,618) — purely statistical, course-not-stated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series in [0, 100]. Penalty-only; base 50.

    Required df columns: volume_ratio, body_pct, close_pos.
    """
    s = pd.Series(50.0, index=df.index)
    s -= np.where(df["volume_ratio"].fillna(0) >= 3.2, 30, 0)
    s -= np.where(df["body_pct"].fillna(0) >= 0.04, 25, 0)
    s -= np.where(df["close_pos"].fillna(0) >= 0.85, 20, 0)
    return s.clip(0, 100)


def make_score(_arg: str | None):
    """Factory matching SCORING_REGISTRY signature: arg → callable(df) → Series."""
    def apply(df: pd.DataFrame) -> pd.Series:
        return score(df)
    apply.__name__ = "attack_quality_anti_course_penalties"
    return apply
