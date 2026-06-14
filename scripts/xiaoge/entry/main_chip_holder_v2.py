"""xiaoge_main_chip_holder v2 — 真三軸（機構 + 大戶累積 + 集保戶下降）+ 月線多頭.

Course source: 權證小哥 ch11 (主力買賣超與集保戶數變化), ch14 (籌碼 K 線分析).

> 「多頭是主力買超，散戶賣超，集保戶數下降。」 (ch11 00:14–00:25)
> 「大戶持股的比率持續性的上升…散戶呢 100 張以下的這持股比率持續性的下降。」 (ch14 02:55–03:11)

v2 改 vs v1：補上集保戶 dataset (`TaiwanStockHoldingSharesPer`)、把三軸都包進來。

## 三軸定義（v2）

1. **機構買超**（DB `main_force_5d` 機構代理）— 跟 v1 一樣，5日累計 > 0 且占成交量 ≥ ratio。
2. **大戶累積**（FinMind shareholding）— `bigholder_pct` 環比上升（這週 > 上週）。
3. **集保戶下降 + 散戶賣**（FinMind shareholding）— `total_people` 環比下降 OR `retail_pct` 環比下降。

## 趨勢 filter
4. 20MA 上揚 + 收盤站上 20MA。

## 注意

- shareholding 是週粒度、daily detector 用「as-of join」拿最新可得 snapshot
- 環比指上週 vs 這週、所以 detector 至少要 2 週資料才開始觸發
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
DEFAULT_SHAREHOLDING_PATH = (
    REPO / "data/analysis/xiaoge/shareholding/2026-04-01_2026-06-12.parquet"
)


def _attach_shareholding(df: pd.DataFrame,
                         shareholding_path: Path = DEFAULT_SHAREHOLDING_PATH) -> pd.DataFrame:
    """As-of join shareholding (weekly) onto daily bars."""
    if not shareholding_path.exists():
        raise FileNotFoundError(
            f"Shareholding parquet missing: {shareholding_path}. "
            f"Run `python3 -m scripts.xiaoge.fetch_shareholding` first."
        )
    sh = pd.read_parquet(shareholding_path)
    sh = sh.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Compute week-over-week change per ticker
    g = sh.groupby("ticker")
    sh["bigholder_pct_prev"] = g["bigholder_pct"].shift(1)
    sh["retail_pct_prev"]    = g["retail_pct"].shift(1)
    sh["total_people_prev"]  = g["total_people"].shift(1)
    sh["bigholder_up"]       = (sh["bigholder_pct"] > sh["bigholder_pct_prev"]).fillna(False)
    sh["retail_down"]        = (sh["retail_pct"] < sh["retail_pct_prev"]).fillna(False)
    sh["total_down"]         = (sh["total_people"] < sh["total_people_prev"]).fillna(False)

    df = df.copy()
    df["_orig_idx"] = df.index

    # merge_asof requires left/right sorted by the asof key (date)
    df_sorted = df.sort_values("trade_date").reset_index(drop=True)
    sh_sorted = sh.sort_values("date").reset_index(drop=True)

    out = pd.merge_asof(
        df_sorted, sh_sorted[["ticker", "date", "bigholder_up", "retail_down", "total_down",
                              "bigholder_pct", "retail_pct", "total_people"]],
        left_on="trade_date", right_on="date", by="ticker",
        direction="backward",
    )
    # Restore original order
    out = out.sort_values("_orig_idx").reset_index(drop=True)
    out = out.drop(columns=["_orig_idx"])
    return out


def detect(df: pd.DataFrame, min_chip_ratio: float = 0.10,
           shareholding_path: Path = DEFAULT_SHAREHOLDING_PATH) -> pd.Series:
    """Return bool Series; True = xiaoge_main_chip_holder v2 long signal.

    Required df columns: ticker, trade_date, close, volume, ma20,
        main_force_5d. (shareholding joined automatically.)
    """
    df2 = _attach_shareholding(df, shareholding_path)

    close = df2["close"]
    ma20 = df2["ma20"]
    main_5d = df2["main_force_5d"]

    vol_5d_sum = df2.groupby("ticker")["volume"].transform(
        lambda s: s.rolling(5, min_periods=5).sum()
    )

    # Axis 1: 機構買超 (5d net > 0 AND ratio ≥ min_chip_ratio)
    chip_ratio = main_5d / vol_5d_sum.replace(0, pd.NA)
    chip_strong = (main_5d > 0) & (chip_ratio >= min_chip_ratio).fillna(False)

    # Axis 2: 大戶累積 (week-over-week bigholder_pct ↑)
    bigholder_up = df2["bigholder_up"].fillna(False)

    # Axis 3: 集保戶下降 OR 散戶比例下降 (二擇一即可、課程精神是同一現象)
    chip_outflow = (df2["total_down"] | df2["retail_down"]).fillna(False)

    # Trend filters
    ma20_prev = ma20.groupby(df2["ticker"]).shift(1)
    ma20_rising = (ma20 > ma20_prev).fillna(False)
    above_ma20 = (close >= ma20).fillna(False)

    # Result: align back to df's original index
    sig = (chip_strong & bigholder_up & chip_outflow & ma20_rising & above_ma20)
    sig.index = df2.index
    # df2 was reindexed by sorting; we need to reorder back to match input df
    # The merge_asof preserves order from left. Re-index to original df.
    return sig.reindex(df.index).fillna(False).astype(bool)
