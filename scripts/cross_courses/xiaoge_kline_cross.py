"""cross_xiaoge_kline — 跨課程交集 detector.

Phase 4 finding (`docs/權證小哥/籌碼技術分析/cross_xiaoge_vs_kline.md`):
- xiaoge 跟 kline_course detector 嚴格重疊只 3.5% → 高度互補
- 36 筆 cross signal 用 xiaoge style hold = +5.70% avg / 58.3% wr
- 跟單獨 detector 比較：3.5× lift, +11.4pp 勝率

User 2026-06-14 拍板 (memory feedback_backtest_strategy_filtering):
- n=10-30 + 勝率 ≥ 65% = actionable
- 跨股 ≥ 5 + 跨月 ≥ 2 robustness 必過
- 反向訊號 (≤35% wr) 跟正面訊號等價值

本 module 提供「給定 xiaoge_signals + kline_signals → 輸出 cross signals」的純函數。
不綁定特定 backtest / exit 規則、上層自己組合。
"""
from __future__ import annotations

import pandas as pd


def cross_signal(xiaoge_sig: pd.Series, kline_sig: pd.Series,
                 df: pd.DataFrame, window: int = 5) -> pd.Series:
    """Return bool Series; True iff both detectors fired within `window` days
    for the same ticker.

    Parameters
    ----------
    xiaoge_sig:
        Bool Series aligned to df, True on xiaoge detector trigger days.
    kline_sig:
        Bool Series aligned to df, True on kline detector trigger days.
    df:
        Bars df with at least `ticker` column.
    window:
        Lookback bars for cross-fire check. Default 5.

    Returns
    -------
    pd.Series of bool, same index as df. True on days where xiaoge fired in
    past N days AND kline fired in past N days (per ticker).
    """
    xs = xiaoge_sig.groupby(df["ticker"]).transform(
        lambda s: s.rolling(window, min_periods=1).max()
    ).astype(bool)
    ks = kline_sig.groupby(df["ticker"]).transform(
        lambda s: s.rolling(window, min_periods=1).max()
    ).astype(bool)
    return (xs & ks).fillna(False)


def cross_signal_strict(xiaoge_sig: pd.Series, kline_sig: pd.Series) -> pd.Series:
    """Strict same-day intersection (no ±N day window)."""
    return (xiaoge_sig & kline_sig).fillna(False)


def find_unique_crosses(xiaoge_sig: pd.Series, kline_sig: pd.Series,
                        df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Return distinct (ticker, signal_date) pairs for cross signals.

    De-duplicates within `window` per ticker so each cross fires once even if
    detectors keep re-firing.
    """
    cross = cross_signal(xiaoge_sig, kline_sig, df, window=window)
    rows = df.loc[cross, ["ticker", "trade_date"]].copy()
    # Keep first cross per ticker per consecutive run
    rows = rows.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    if rows.empty:
        return rows
    rows["gap"] = rows.groupby("ticker")["trade_date"].diff().dt.days.fillna(999)
    rows["new_cross"] = (rows["gap"] > window).astype(int)
    return rows[rows["new_cross"] == 1][["ticker", "trade_date"]].reset_index(drop=True)
