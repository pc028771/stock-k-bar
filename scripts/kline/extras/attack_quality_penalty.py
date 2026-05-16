"""EXTRA: Backtest-derived attack-quality scoring (NOT course-faithful).

**本檔案內容非課程定義**，從 `scripts/kline/scoring/attack_quality.py` 搬移
到 extras。

## 為什麼搬到這裡（audit C4）
課程（突破跌破 — 突破意義的釐清）明文表示：
> 「對於K線圖來說，價格才是最重要的事情，不需要加上成交量」
> 「與這一根突破的K線是否長紅、有沒有上影線都無關」

本檔對 entry-side ranking 套用 volume_ratio、body_pct、close_pos 罰分，
**直接違反課程立場**，也違反 CLAUDE.md「禁止將回測分析結論套用在個股
操作建議上」。

實證觀察：top-N analysis 顯示 scanner_score 反而是 anti-signal
（top-5 win 37.8% < baseline 39.4% < bottom-5 win 40.7%）。

## 為什麼仍保留
作 backtest 對照、研究用。default OFF；需透過
`--extras attack_quality_penalty` 啟用。

## 校準來源
Spearman correlation against trade_return_net over the course-defined exit
simulation (n≈6,618). Thresholds (17, 3.2, 0.04, 0.85) picked by inflection
points in correlation curve — purely statistical, course-not-stated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def score(df: pd.DataFrame) -> pd.Series:
    """Returns float Series in [0, 100]. Higher = better attack quality.

    Required df columns: pre_breakout_trend_days, volume_ratio, body_pct, close_pos.
    """
    s = pd.Series(50.0, index=df.index)
    s += np.where(df["pre_breakout_trend_days"].fillna(0) >= 17, 25, 0)
    s -= np.where(df["volume_ratio"].fillna(0) >= 3.2, 30, 0)
    s -= np.where(df["body_pct"].fillna(0) >= 0.04, 25, 0)
    s -= np.where(df["close_pos"].fillna(0) >= 0.85, 20, 0)
    return s.clip(0, 100)


def make_score(_arg: str | None):
    """Factory matching SCORING_REGISTRY signature: arg → callable(df) → Series."""
    def apply(df: pd.DataFrame) -> pd.Series:
        return score(df)
    apply.__name__ = "attack_quality_penalty"
    return apply
