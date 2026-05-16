"""EXTRA: 中樞型態跌破 — quantitative consolidation-break exit (NOT for entry/exit per course).

**本檔案內容非課程定義**，從 `scripts/kline/exit/consolidation_breakdown.py`
搬移到 extras。

## 為什麼搬到這裡（audit C7）
課程（型態學 06-中樞型態）對中樞型態的明確立場是：
> "Middle continuation; **NOT for trade entry/exit**; just 保持冷靜 during
> consolidation"

換言之，課程說中樞型態本身**不是**進出場依據。原檔以 10-bar narrow range
+ 8% range threshold + black K + break-low 構造出場條件，**這些 10、8%
完全是我們自訂的量化代理**，課程沒這樣量化也沒這樣用。

## 為什麼仍保留
作 backtest 對照、實驗用。default OFF；需透過
`--extras consolidation_breakdown` 啟用。

## 量化代理（非課程）
- CONSOLIDATION_DAYS = 10
- CONSOLIDATION_RANGE_MAX = 0.08

Required df columns: ticker, close, low, high, open.
"""
from __future__ import annotations

import pandas as pd

CONSOLIDATION_DAYS = 10                # Proxy (non-course): ~1-2 weeks window
CONSOLIDATION_RANGE_MAX = 0.08          # Proxy (non-course): 8% range = narrow


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = consolidation breakdown on that bar."""
    g = df.groupby("ticker", group_keys=False)

    prior_max = pd.Series(
        g["high"].shift(1).rolling(CONSOLIDATION_DAYS, min_periods=CONSOLIDATION_DAYS).max()
        .reset_index(level=0, drop=True).values,
        index=df.index,
    )
    prior_min = pd.Series(
        g["low"].shift(1).rolling(CONSOLIDATION_DAYS, min_periods=CONSOLIDATION_DAYS).min()
        .reset_index(level=0, drop=True).values,
        index=df.index,
    )
    prior_mean = pd.Series(
        g["close"].shift(1).rolling(CONSOLIDATION_DAYS, min_periods=CONSOLIDATION_DAYS).mean()
        .reset_index(level=0, drop=True).values,
        index=df.index,
    )

    range_pct = (prior_max - prior_min) / prior_mean.replace(0, float("nan"))
    was_consolidating = range_pct <= CONSOLIDATION_RANGE_MAX

    is_black = df["close"] < df["open"]
    breaks_below = df["close"] < prior_min

    return (was_consolidating & is_black & breaks_below).fillna(False)


def make_mark(_arg: str | None):
    """Factory matching EXIT_REGISTRY signature."""
    def apply(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
        return mark(df, entries)
    apply.__name__ = "consolidation_breakdown"
    return apply
