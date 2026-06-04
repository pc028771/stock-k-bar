"""均線全順向 + 站 MA5 之上 scanner.

老師教法: 均線全順向 (MA5 > MA10 > MA20 > MA60) + close 站均線之上 = 多頭結構確立.

User 6/4 拍板:
  - MA5 > MA10 > MA20 > MA60 (嚴格排序)
  - close >= MA5 (站最高均線、自動站全部)
  - 不限週主推族群、走 sector_all
  - filter 結果 ≠ 必看、傳產金融老師肉眼跳

來源: project-teacher-uniform-ma-44-20260604
"""
from __future__ import annotations

import pandas as pd


def run_uniform_ma_above(
    df: pd.DataFrame,
    allowed_tickers: set[str] | None = None,
    target_date: str | None = None,
    ticker_col: str = "ticker",
) -> pd.DataFrame:
    """掃描均線全順向 + 站 MA5 之上的標的.

    Parameters
    ----------
    df : pd.DataFrame
        含 ticker / trade_date / close / ma5 / ma10 / ma20 / ma60 欄位
    allowed_tickers : set[str] | None
        universe 限制 (None = 全部); 預設 sector_all
    target_date : str | None
        指定收盤日 (YYYY-MM-DD); 預設 max date
    ticker_col : str
        ticker 欄位名稱

    Returns
    -------
    DataFrame 欄位:
        ticker, close, ma5, ma10, ma20, ma60,
        dist_ma20_pct, dist_ma60_pct
    """
    if df.empty:
        return pd.DataFrame()

    date_col = "trade_date" if "trade_date" in df.columns else "date"

    if target_date:
        df = df[df[date_col] == target_date]
    else:
        max_d = df[date_col].max()
        df = df[df[date_col] == max_d]

    if allowed_tickers is not None and ticker_col in df.columns:
        df = df[df[ticker_col].isin(allowed_tickers)]

    if df.empty:
        return pd.DataFrame()

    mask = (
        df["ma5"].notna() & df["ma10"].notna()
        & df["ma20"].notna() & df["ma60"].notna()
        & (df["ma5"] > df["ma10"])
        & (df["ma10"] > df["ma20"])
        & (df["ma20"] > df["ma60"])
        & (df["close"] >= df["ma5"])
    )
    hits = df[mask].copy()
    if hits.empty:
        return pd.DataFrame()

    hits["dist_ma20_pct"] = ((hits["close"] - hits["ma20"]) / hits["ma20"] * 100).round(1)
    hits["dist_ma60_pct"] = ((hits["close"] - hits["ma60"]) / hits["ma60"] * 100).round(1)

    cols = [ticker_col, "close", "ma5", "ma10", "ma20", "ma60",
            "dist_ma20_pct", "dist_ma60_pct"]
    cols = [c for c in cols if c in hits.columns]
    return hits[cols].sort_values("dist_ma20_pct").reset_index(drop=True)
