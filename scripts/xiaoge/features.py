"""Bollinger band features for 權證小哥 (xiaoge) course.

Source: docs/權證小哥/籌碼技術分析/快速上手筆記.md, detector_spec.md
Course refs: ch06 (布林軌道說明), ch07 (型態與應用方法)

> 「布林軌道打開，股價沿著上軌前進，那周圍點就是起漲點。」(ch03 01:35)
> 「布林軌道是一個由 20MA 加減 2 個標準差所形成的通道。」(ch06)

Bandwidth scale (老師原話、ch06):
    - bandwidth < 5  → 很窄（收斂、整理）
    - bandwidth ~ 10 → 正常
    - bandwidth ~ 20 → 寬
    - bandwidth ~ 30 → 很寬（噴出後可能進入震盪）

Formula: bandwidth = (bb_upper - bb_lower) / bb_lower * 100
"""
from __future__ import annotations

import pandas as pd


BB_PERIOD = 20
BB_STDDEV = 2.0


def add_bollinger(df: pd.DataFrame) -> pd.DataFrame:
    """Add bb_mid / bb_upper / bb_lower / bb_bandwidth columns.

    Required df columns: ticker, trade_date, close. Sorted by (ticker, trade_date).
    """
    out = df.copy()
    grp = out.groupby("ticker")["close"]
    mid = grp.transform(lambda s: s.rolling(BB_PERIOD, min_periods=BB_PERIOD).mean())
    std = grp.transform(lambda s: s.rolling(BB_PERIOD, min_periods=BB_PERIOD).std(ddof=0))
    out["bb_mid"] = mid
    out["bb_upper"] = mid + BB_STDDEV * std
    out["bb_lower"] = mid - BB_STDDEV * std
    # bandwidth normalized by lower band so it represents % range from lower→upper
    out["bb_bandwidth"] = (out["bb_upper"] - out["bb_lower"]) / out["bb_lower"] * 100.0
    return out


def add_squeeze_features(df: pd.DataFrame, squeeze_lookback: int = 10,
                        squeeze_threshold: float = 12.0) -> pd.DataFrame:
    """Add bb_in_squeeze flag.

    bb_in_squeeze[t] = True iff past `squeeze_lookback` bars all have bandwidth ≤ threshold.

    Threshold 12 (slight relaxation of 老師's 10「正常」line — gives some breathing room).
    See detector_spec.md detector 1 condition 2.
    """
    out = df.copy()
    grp = out.groupby("ticker")["bb_bandwidth"]
    max_recent = grp.transform(
        lambda s: s.rolling(squeeze_lookback, min_periods=squeeze_lookback).max()
    )
    out["bb_in_squeeze"] = max_recent <= squeeze_threshold
    return out
