"""均線全順向 + 站 MA5 之上 + 基本指標濾網 scanner.

老師教法: 均線全順向 (MA5 > MA10 > MA20 > MA60) + close 站均線之上 = 多頭結構確立.

User 6/4 拍板 (技術核心):
  - MA5 > MA10 > MA20 > MA60 (嚴格排序)
  - close >= MA5 (站最高均線、自動站全部)
  - 不限週主推族群、走 sector_all

老師選股軟體推測條件 (反向工程 reverse_engineer_uniform_ma 推出、F1 最佳組合):
  - 成交額 ≥ 25,000,000 (流動性過濾)
  - 距 MA20 < 12%  (排除追高末端)
  - 距 MA60 < 40%  (排除過熱)
  - 20d 漲幅 ≤ 25% (反直覺、老師選漲少的、不追)

6/3 驗證: 全市場 434 → 套濾網 145 → ∩老師44=35 (F1 0.370)
6/3 不套濾網: 434 → ∩44=41

來源: project-teacher-uniform-ma-44-20260604
       docs/主力大課程/reverse_engineer_uniform_ma_findings_20260604.md
"""
from __future__ import annotations

import pandas as pd

# 反向工程拍板門檻 (F1 最佳)
DEFAULT_MIN_TURNOVER = 25_000_000      # 成交額下限
DEFAULT_MAX_DIST_MA20_PCT = 12.0       # 距 MA20 上限 %
DEFAULT_MAX_DIST_MA60_PCT = 40.0       # 距 MA60 上限 %
DEFAULT_MAX_RETURN_20D_PCT = 25.0      # 20d 漲幅上限 %


def run_uniform_ma_above(
    df: pd.DataFrame,
    allowed_tickers: set[str] | None = None,
    target_date: str | None = None,
    ticker_col: str = "ticker",
    apply_extra_filters: bool = True,
    min_turnover: float = DEFAULT_MIN_TURNOVER,
    max_dist_ma20_pct: float = DEFAULT_MAX_DIST_MA20_PCT,
    max_dist_ma60_pct: float = DEFAULT_MAX_DIST_MA60_PCT,
    max_return_20d_pct: float = DEFAULT_MAX_RETURN_20D_PCT,
) -> pd.DataFrame:
    """掃描均線全順向 + 站 MA5 + 基本指標濾網.

    Parameters
    ----------
    df : pd.DataFrame
        含 ticker / trade_date / close / volume / ma5/10/20/60 欄位 (含歷史以算 20d 漲幅)
    allowed_tickers : set[str] | None
        universe 限制 (None = 全部); 預設 sector_all
    target_date : str | None
        指定收盤日 (YYYY-MM-DD); 預設 max date
    apply_extra_filters : bool
        是否套用 4 項基本指標濾網 (預設 True、跟老師 snapshot 對齊)
    min_turnover / max_dist_ma20_pct / max_dist_ma60_pct / max_return_20d_pct
        4 項濾網門檻、不傳則用 DEFAULT (F1 最佳)

    Returns
    -------
    DataFrame 欄位:
        ticker, close, ma5, ma10, ma20, ma60,
        dist_ma20_pct, dist_ma60_pct, return_20d_pct, turnover
    """
    if df.empty:
        return pd.DataFrame()

    date_col = "trade_date" if "trade_date" in df.columns else "date"

    # 算 20d 漲幅 (在過濾日期前算、需要歷史)
    if "close" in df.columns and ticker_col in df.columns and apply_extra_filters:
        df = df.sort_values([ticker_col, date_col]).copy()
        df["close_20d_ago"] = df.groupby(ticker_col)["close"].shift(20)
        df["return_20d_pct"] = (df["close"] / df["close_20d_ago"] - 1) * 100
    else:
        df = df.copy()
        df["return_20d_pct"] = None

    # 過濾到目標日
    if target_date:
        df = df[df[date_col] == target_date]
    else:
        max_d = df[date_col].max()
        df = df[df[date_col] == max_d]

    if allowed_tickers is not None and ticker_col in df.columns:
        df = df[df[ticker_col].isin(allowed_tickers)]

    if df.empty:
        return pd.DataFrame()

    # 核心: 均線全順向 + close 站 MA5
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
    if "volume" in hits.columns:
        hits["turnover"] = (hits["close"] * hits["volume"]).round(0)
    else:
        hits["turnover"] = None

    # 套用基本指標濾網 (反向工程出的老師條件)
    if apply_extra_filters:
        extra_mask = pd.Series(True, index=hits.index)
        if "turnover" in hits.columns and hits["turnover"].notna().any():
            extra_mask &= (hits["turnover"] >= min_turnover)
        extra_mask &= (hits["dist_ma20_pct"] <= max_dist_ma20_pct)
        extra_mask &= (hits["dist_ma60_pct"] <= max_dist_ma60_pct)
        if hits["return_20d_pct"].notna().any():
            extra_mask &= (hits["return_20d_pct"] <= max_return_20d_pct)
        hits = hits[extra_mask]

    if hits.empty:
        return pd.DataFrame()

    cols = [ticker_col, "close", "ma5", "ma10", "ma20", "ma60",
            "dist_ma20_pct", "dist_ma60_pct", "return_20d_pct", "turnover"]
    cols = [c for c in cols if c in hits.columns]
    return hits[cols].sort_values("dist_ma20_pct").reset_index(drop=True)
