"""EXTRA: Crude `prior_low_20` neckline-break proxy (NOT course-faithful).

**本檔案內容非課程定義**，從 `scripts/kline/exit/neckline_break.py` 搬移
到 extras。

## 為什麼搬到這裡（audit C3）
課程（型態學 頭部型態 + 行進ing 事件七）對「頸線」的定義是：
**季線下彎後的前一個低點 AND 該低點上方有 ≥ 3 個月套牢**。

本檔以 `prior_low_20`（過去 20 日 rolling 最低）做近似，**不滿足課程兩條
件**。同時系統內已有課程精確版 `ma60_neckline.py`（季線下彎 + 套牢條件）。
讓兩者並存時，本檔的觸發更敏感，會先觸發、掩蓋課程版的行為。

## 為什麼仍保留
backtest 觀察、與課程版對照用。default OFF；需透過
`--extras neckline_break_crude_proxy` 啟用。

## 課程定義版本
請使用 `kline.exit.ma60_neckline`。

Required df columns: ticker, close, prior_low_20.
"""
from __future__ import annotations

import pandas as pd


def mark(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
    """Returns bool Series. True = prior_low_20 break confirmed two days in a row."""
    broke_today = df["close"] < df["prior_low_20"]
    broke_yesterday = broke_today.groupby(df["ticker"]).shift(1).fillna(False)
    return (broke_yesterday & broke_today).fillna(False)


def make_mark(_arg: str | None):
    """Factory matching EXIT_REGISTRY signature."""
    def apply(df: pd.DataFrame, entries: pd.Series | None = None) -> pd.Series:
        return mark(df, entries)
    apply.__name__ = "neckline_break_crude_proxy"
    return apply
