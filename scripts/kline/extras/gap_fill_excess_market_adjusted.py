"""EXTRA: Same-day market-adjusted excess-gap-then-close-down exit (NOT course-faithful).

## 課程立場
課程的「攻擊跳空回補」(跳空篇二) 定義是：**收盤跌破攻擊跳空的下緣
(prev_high)**，且這是跨日比較。課程從未把市場相對表現 (market_open_ret)
納入個股 attack-gap 判斷。

## 為什麼放這裡
這個檔原本叫 `gap_fill`，使用 (stock_open - market_open_ret) ≥ 2% 作
"excess gap"，再加當日收盤 < 前日收盤判斷 "gap filled"——是**同日 gap
and close-down** 的市場相對版本，不是課程定義的攻擊跳空。

課程定義的版本由 `kline.exit.gap_attack_filled` 提供 (跳空篇二)。本檔
保留作 backtest 對照用，但 default OFF。

## 觀察證據
audit `docs/analysis/2026-05-16-course-compliance-audit.md` C2 指出本檔
與課程定義同時掛在 strong_attack group 時，會率先觸發、掩蓋課程版本的
表現。

## 參數
`--extras gap_fill_excess_market_adjusted` （無參數）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EXCESS_GAP_MIN = 0.02  # 2% excess gap threshold (non-course)


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = excess-market-gap-then-close-down on that bar.

    `entries` accepted for interface uniformity.
    """
    prev_close = df["prev_close"].replace(0, np.nan)
    stock_gap = df["open"] / prev_close - 1
    excess_gap = stock_gap - df["market_open_ret"].fillna(0.0)
    triggered = (excess_gap >= EXCESS_GAP_MIN) & (df["close"] < df["prev_close"])
    return triggered.fillna(False)


def make_mark(_arg: str | None):
    """Factory matching EXIT_REGISTRY signature."""
    def apply(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
        return mark(df, entries)
    apply.__name__ = "gap_fill_excess_market_adjusted"
    return apply
