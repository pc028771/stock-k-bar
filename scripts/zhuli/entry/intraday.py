"""F 當沖 entry signal — 主力大 Ch5-1/Ch5-2/Ch5-3.

Course source: strategy-indicators.md §F 當沖策略

⚠️ Scanner 只做「前夜選股」(日 K 級)；盤中執行（5 分 K + VWAP + 突破第一根 K 高點）
   不在 scanner 範圍，由 user 手動執行。

Logic:
    1. MA5 > MA10 > MA20 + 三條上彎
    2. 近 2 日量 > 2 萬張
    3. 近 3 日振幅 > 8%
    4. 近 3 日周轉率 > 20%
    5. 離月線 < 30%
    6. 距 60D 前高 < 10% (Ch5-2 精選)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from zhuli.config import IntradayConfig


def _load_shareholding(db_path: Path) -> pd.DataFrame:
    try:
        with sqlite3.connect(str(db_path), timeout=15) as conn:
            return pd.read_sql_query(
                "SELECT ticker, trade_date, shares_issued FROM stock_shareholding", conn
            )
    except Exception:
        return pd.DataFrame(columns=["ticker", "trade_date", "shares_issued"])


def detect(
    df: pd.DataFrame,
    cfg: Optional[IntradayConfig] = None,
    db_path: Optional[Path] = None,
) -> pd.DataFrame:
    if cfg is None:
        cfg = IntradayConfig()
    if db_path is None:
        from kline.bars import DEFAULT_DB_PATH
        db_path = DEFAULT_DB_PATH

    df = df.copy()
    g = df.groupby("ticker", group_keys=False)

    # 近 2 日量
    df["vol_lots"] = df["volume"] / 1000  # 張
    df["vol_2d_min"] = g["vol_lots"].rolling(2, min_periods=2).min().reset_index(level=0, drop=True)

    # 近 3 日振幅 (H-L)/L
    df["h_3d"] = g["high"].rolling(3, min_periods=3).max().reset_index(level=0, drop=True)
    df["l_3d"] = g["low"].rolling(3, min_periods=3).min().reset_index(level=0, drop=True)
    df["range_3d"] = (df["h_3d"] - df["l_3d"]) / df["l_3d"].replace(0, np.nan)

    # 近 3 日 volume 累計 (用於周轉率)
    df["vol_3d_sum"] = g["volume"].rolling(3, min_periods=3).sum().reset_index(level=0, drop=True)

    # 前 60 日高
    df["prev_high_60d"] = (
        g["high"].rolling(cfg.prev_high_lookback_days, min_periods=20)
        .max().reset_index(level=0, drop=True)
    )
    df["dist_from_prev_high"] = (df["prev_high_60d"] - df["close"]) / df["prev_high_60d"]

    # Ch5-2 量能突破倍率：今日量 / 前高那天的量
    # 「右下角近期量 > 左邊前高的量」「衝擊前高需要更大量」
    def _prev_high_day_vol(group: pd.DataFrame) -> pd.Series:
        n = len(group)
        out = np.full(n, np.nan)
        lookback = cfg.prev_high_lookback_days
        highs = group["high"].to_numpy()
        vols = group["volume"].to_numpy()
        for i in range(20, n):
            start = max(0, i - lookback)
            window_high = highs[start:i]   # exclude today
            window_vol = vols[start:i]
            if len(window_high) < 20:
                continue
            max_idx = int(np.argmax(window_high))
            out[i] = window_vol[max_idx]
        return pd.Series(out, index=group.index)

    df["prev_high_day_vol"] = g.apply(_prev_high_day_vol).reset_index(level=0, drop=True)
    df["breakout_vol_ratio"] = df["volume"] / df["prev_high_day_vol"].replace(0, np.nan)

    # 離月線
    df["dist_from_ma20"] = (df["close"] - df["ma20"]).abs() / df["ma20"]

    # 加入 shares_issued 算周轉率
    shares_df = _load_shareholding(db_path)
    if not shares_df.empty:
        shares_df["trade_date"] = pd.to_datetime(shares_df["trade_date"]).dt.strftime("%Y-%m-%d")
        df["trade_date_str"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        # forward-fill shares within ticker
        merged = df.merge(
            shares_df, left_on=["ticker", "trade_date_str"], right_on=["ticker", "trade_date"],
            how="left", suffixes=("", "_shares")
        )
        # forward fill missing
        merged = merged.sort_values(["ticker", "trade_date"])
        merged["shares_issued"] = merged.groupby("ticker")["shares_issued"].ffill()
        df = merged
    else:
        df["shares_issued"] = np.nan

    df["turnover_3d"] = df["vol_3d_sum"] / df["shares_issued"].replace(0, np.nan)

    # Mask
    mask = pd.Series(True, index=df.index)

    if cfg.require_ma_alignment:
        mask &= (df["ma5"] > df["ma10"]) & (df["ma10"] > df["ma20"])
        # 三條上彎用扣抵預判 (比 slope 提早 1-2 天)
        if "ma5_will_rise" in df.columns:
            mask &= df["ma5_will_rise"].fillna(False)
            mask &= df["ma10_will_rise"].fillna(False)
            mask &= df["ma20_will_rise"].fillna(False)
        else:
            for s in ["ma5_slope_5d", "ma10_slope_5d", "ma20_slope_5d"]:
                if s in df.columns:
                    mask &= df[s].fillna(-1) > 0

    mask &= df["vol_2d_min"].fillna(0) > cfg.min_vol_2d_lots
    mask &= df["range_3d"].fillna(0) > cfg.min_range_3d
    mask &= df["turnover_3d"].fillna(0) > cfg.min_turnover_3d
    mask &= df["dist_from_ma20"].fillna(99) < cfg.max_dist_from_ma20
    mask &= df["dist_from_prev_high"].fillna(99) < cfg.max_dist_from_prev_high
    mask &= df["close"] >= cfg.min_close

    # Ch5-2 量能突破倍率（require_breakout_vol=True 才啟用）
    if cfg.require_breakout_vol:
        mask &= df["breakout_vol_ratio"].fillna(0) >= cfg.min_breakout_vol_ratio

    signals = df[mask].copy()
    if signals.empty:
        return pd.DataFrame(columns=[
            "ticker", "signal_date", "close", "prev_high_60d",
            "dist_from_prev_high", "vol_2d_min", "range_3d", "turnover_3d",
            "dist_from_ma20", "stop_loss", "entry_note",
        ])

    out = pd.DataFrame({
        "ticker": signals["ticker"],
        "signal_date": signals["trade_date"],
        "close": signals["close"],
        "prev_high_60d": signals["prev_high_60d"],
        "dist_from_prev_high": signals["dist_from_prev_high"],
        "vol_2d_min": signals["vol_2d_min"],
        "range_3d": signals["range_3d"],
        "turnover_3d": signals["turnover_3d"],
        "dist_from_ma20": signals["dist_from_ma20"],
        "breakout_vol_ratio": signals["breakout_vol_ratio"],
        "stop_loss": signals["low"],  # 盤中：第一根 5 分 K 低 (此 scanner 用日 K low 當前夜參考)
    })
    out["entry_note"] = out.apply(
        lambda r: (
            f"close={r['close']:.2f} 距前高{r['dist_from_prev_high']*100:.1f}%; "
            f"vol2d>{r['vol_2d_min']:.0f}張; range3d={r['range_3d']*100:.1f}%; "
            f"turn3d={r['turnover_3d']*100:.1f}%"
        ),
        axis=1,
    )
    out = out.sort_values(["signal_date", "dist_from_prev_high"], ascending=[False, True]).reset_index(drop=True)
    return out
